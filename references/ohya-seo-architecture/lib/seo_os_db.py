#!/usr/bin/env python3
"""Shared PostgreSQL helper for Ohya SEO Growth OS.

Safety rules:
- Never print DATABASE_URI / POSTGRES_URL / connection strings.
- Default commands are read-only or dry-run unless explicitly told otherwise.
- Production migrations are blocked by CLI policy; helpers only provide primitives.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

try:
    import psycopg
    from psycopg.rows import dict_row
except Exception:  # pragma: no cover
    psycopg = None
    dict_row = None

ROOT = Path('/Users/garyyang/clients/ohya')
MIGRATIONS_DIR = ROOT / 'data' / 'seo-os' / 'migrations'
SAFE_ENV_KEYS = (
    'SEO_OS_DATABASE_URI',
    'DATABASE_URI',
    'POSTGRES_URL',
    'POSTGRES_URI',
    'PGDATABASE',
)


class SeoOsDbError(RuntimeError):
    pass


@dataclass(frozen=True)
class DbConfig:
    uri: str | None
    source: str | None

    @property
    def configured(self) -> bool:
        return bool(self.uri)


def load_dotenv(path: str | Path) -> None:
    """Load env vars from a .env-like file without overriding existing env.

    Values are never printed by this helper.
    """
    p = Path(path)
    if not p.exists():
        return
    for raw in p.read_text(errors='ignore').splitlines():
        line = raw.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def load_default_env_files() -> None:
    """Load known non-secret paths. Does not print content."""
    for p in (
        ROOT / 'data' / 'seo-os' / '.env.local',
        ROOT / '.env',
        ROOT / 'profiles' / 'coordinator' / '.env',
        ROOT / 'repos' / 'ohya-payload' / '.env',
    ):
        load_dotenv(p)


def get_db_config(load_env: bool = True) -> DbConfig:
    if load_env:
        load_default_env_files()
    for key in ('SEO_OS_DATABASE_URI', 'DATABASE_URI', 'POSTGRES_URL', 'POSTGRES_URI'):
        val = os.environ.get(key)
        if val:
            return DbConfig(uri=val, source=key)
    # libpq-style env can be enough for psycopg/psql.
    if os.environ.get('PGDATABASE') or os.environ.get('PGHOST'):
        return DbConfig(uri=None, source='PG*')
    return DbConfig(uri=None, source=None)


def redacted_config_status() -> dict[str, Any]:
    load_default_env_files()
    present = {key: bool(os.environ.get(key)) for key in SAFE_ENV_KEYS}
    return {
        'configured': any(present.values()) or bool(os.environ.get('PGHOST')),
        'source': get_db_config(load_env=False).source,
        'present_keys': present,
        'pg_host_present': bool(os.environ.get('PGHOST')),
        'secret_redacted': True,
    }


@contextmanager
def connect(autocommit: bool = False):
    if psycopg is None:
        raise SeoOsDbError('psycopg is not installed')
    cfg = get_db_config()
    if not cfg.configured:
        raise SeoOsDbError('No DB connection configured. Set SEO_OS_DATABASE_URI or DATABASE_URI in environment.')
    if cfg.uri:
        conn = psycopg.connect(cfg.uri, autocommit=autocommit, row_factory=dict_row)
    else:
        conn = psycopg.connect(autocommit=autocommit, row_factory=dict_row)
    try:
        yield conn
    finally:
        conn.close()


def query_json(sql: str, params: Iterable[Any] | None = None) -> list[dict[str, Any]]:
    """Execute SQL and return rows as dicts.

    Commits successful statements, including INSERT/UPDATE ... RETURNING used by
    the CLI helpers. This keeps each CLI invocation atomic and visible to the
    next invocation.
    """
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params or [])
            rows = [] if cur.description is None else list(cur.fetchall())
        conn.commit()
        return rows


def execute(sql: str, params: Iterable[Any] | None = None, *, dry_run: bool = False) -> dict[str, Any]:
    if dry_run:
        return {'dry_run': True, 'sql_preview': sql[:500], 'params_count': len(list(params or []))}
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params or [])
            rowcount = cur.rowcount
        conn.commit()
    return {'dry_run': False, 'rowcount': rowcount}


def split_sql_statements(sql: str) -> list[str]:
    """Small SQL splitter good enough for current migrations.

    It ignores semicolons in single quoted strings and line comments.
    """
    statements: list[str] = []
    buf: list[str] = []
    in_single = False
    in_line_comment = False
    i = 0
    while i < len(sql):
        ch = sql[i]
        nxt = sql[i + 1] if i + 1 < len(sql) else ''
        if in_line_comment:
            buf.append(ch)
            if ch == '\n':
                in_line_comment = False
            i += 1
            continue
        if not in_single and ch == '-' and nxt == '-':
            in_line_comment = True
            buf.append(ch); buf.append(nxt); i += 2
            continue
        if ch == "'":
            in_single = not in_single
            buf.append(ch); i += 1
            continue
        if ch == ';' and not in_single:
            stmt = ''.join(buf).strip()
            if stmt:
                statements.append(stmt + ';')
            buf = []
            i += 1
            continue
        buf.append(ch); i += 1
    tail = ''.join(buf).strip()
    if tail:
        statements.append(tail)
    return statements


def validate_sql_files(paths: list[Path]) -> list[dict[str, Any]]:
    results = []
    for path in paths:
        text = path.read_text()
        statements = split_sql_statements(text)
        issues = []
        if not statements:
            issues.append('no statements')
        if path.name.startswith('002') and 'CREATE SCHEMA IF NOT EXISTS seo_os' not in text:
            # Not fatal if applied after 001, but dry-run plan should make dependency explicit.
            issues.append('depends on 001_create_seo_os_core.sql for schema/tasks')
        results.append({
            'path': str(path),
            'statements': len(statements),
            'issues': issues,
            'ok': not any(i == 'no statements' for i in issues),
        })
    return results


def migration_files() -> list[Path]:
    return sorted(MIGRATIONS_DIR.glob('*.sql'))


def psql_available() -> bool:
    return subprocess.run(['bash', '-lc', 'command -v psql >/dev/null 2>&1']).returncode == 0


def table_names() -> list[str]:
    rows = query_json(
        """
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'seo_os'
        ORDER BY table_name
        """
    )
    return [r['table_name'] for r in rows]


def looks_like_production_uri() -> bool:
    cfg = get_db_config()
    uri = cfg.uri or ''
    lowered = uri.lower()
    return any(token in lowered for token in ['zeabur', 'production', 'prod', 'amazonaws', 'render.com'])


def assert_not_production_unless_allowed() -> None:
    if looks_like_production_uri() and os.environ.get('SEO_OS_ALLOW_PRODUCTION') != 'I_UNDERSTAND':
        raise SeoOsDbError('Connection looks like production. Refusing write action without SEO_OS_ALLOW_PRODUCTION=I_UNDERSTAND')


def _maybe_uuid(value: Any) -> uuid.UUID | None:
    if value in (None, ''):
        return None
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError):
        return None


def _json_default(value: Any) -> str:
    if isinstance(value, (datetime, uuid.UUID)):
        return str(value)
    return str(value)


def _json_dumps(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False, default=_json_default)


def _result_status(result: dict[str, Any]) -> str:
    if result.get('failed_count', 0) or result.get('ok') is False:
        return 'failed'
    if result.get('warning_count', 0):
        return 'warning'
    return 'passed'


def record_workflow_event(
    *,
    task_id: uuid.UUID | str | None = None,
    agent_run_id: uuid.UUID | str | None = None,
    event_type: str,
    actor_type: str = 'system',
    actor_id: str = 'seo-os',
    message: str | None = None,
    metadata: dict[str, Any] | None = None,
    allow_production: bool = False,
) -> dict[str, Any]:
    """Insert one workflow event and return it.

    Production-looking connections are blocked unless allow_production=True and
    SEO_OS_ALLOW_PRODUCTION=I_UNDERSTAND is set by the caller's approved runbook.
    """
    if not allow_production:
        assert_not_production_unless_allowed()
    task_uuid = _maybe_uuid(task_id)
    run_uuid = _maybe_uuid(agent_run_id)
    rows = query_json(
        """
        INSERT INTO seo_os.workflow_events (task_id, agent_run_id, event_type, actor_type, actor_id, message, metadata)
        VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb)
        RETURNING id, task_id, agent_run_id, event_type, created_at
        """,
        [task_uuid, run_uuid, event_type, actor_type, actor_id, message, _json_dumps(metadata or {})],
    )
    return rows[0] if rows else {}


def record_guardrail_result(
    result: dict[str, Any],
    *,
    context_path: str | None = None,
    result_path: str | None = None,
    source: str = 'seo-guardrail',
    allow_production: bool = False,
) -> dict[str, Any]:
    """Persist one seo-guardrail result + per-rule checks into seo_os.

    This is intentionally append-only and idempotent by result_id. It does not
    mutate task status; dispatch wrappers decide whether to stop or continue.
    """
    if not allow_production:
        assert_not_production_unless_allowed()

    task_ref = str(result.get('task_id') or 'local-task')
    task_uuid = _maybe_uuid(task_ref)
    if task_uuid:
        exists = query_json('SELECT id FROM seo_os.tasks WHERE id=%s LIMIT 1', [task_uuid])
        if not exists:
            task_uuid = None

    agent_run_uuid = _maybe_uuid(result.get('agent_run_id'))
    if agent_run_uuid:
        exists = query_json('SELECT id FROM seo_os.agent_runs WHERE id=%s LIMIT 1', [agent_run_uuid])
        if not exists:
            agent_run_uuid = None

    status = _result_status(result)
    event_type = 'guardrail_passed' if status == 'passed' else 'guardrail_blocked'
    event = record_workflow_event(
        task_id=task_uuid,
        agent_run_id=agent_run_uuid,
        event_type=event_type,
        actor_type='system',
        actor_id=source,
        message=f"{source} {result.get('stage')} {status}",
        metadata={
            'result_id': result.get('result_id'),
            'task_ref': task_ref,
            'stage': result.get('stage'),
            'ok': result.get('ok'),
            'failure_state': result.get('failure_state'),
            'failed_guardrails': result.get('failed_guardrails') or [],
        },
        allow_production=True,
    )

    rid = _maybe_uuid(result.get('result_id')) or uuid.uuid4()
    checked_at = result.get('checked_at')
    rows = query_json(
        """
        INSERT INTO seo_os.guardrail_results (
          result_id, task_id, task_ref, agent_run_id, workflow_event_id,
          checked_at, stage, status, ok, next_allowed, failure_state,
          failed_guardrails, checked_count, passed_count, failed_count, warning_count,
          context_sha256, context_path, result_path, source, local_only,
          production_side_effect, secret_redacted, result_json, metadata
        ) VALUES (
          %s, %s, %s, %s, %s,
          COALESCE(%s::timestamptz, now()), %s, %s, %s, %s, %s,
          %s::text[], %s, %s, %s, %s,
          %s, %s, %s, %s, %s,
          %s, %s, %s::jsonb, %s::jsonb
        )
        ON CONFLICT (result_id) DO UPDATE SET
          result_path = COALESCE(EXCLUDED.result_path, seo_os.guardrail_results.result_path),
          metadata = seo_os.guardrail_results.metadata || EXCLUDED.metadata
        RETURNING id, result_id, task_ref, stage, status, ok, workflow_event_id, checked_at
        """,
        [
            rid, task_uuid, task_ref, agent_run_uuid, event.get('id'),
            checked_at, result.get('stage'), status, bool(result.get('ok')), bool(result.get('next_allowed')), result.get('failure_state'),
            result.get('failed_guardrails') or [], int(result.get('checked_count') or 0), int(result.get('passed_count') or 0), int(result.get('failed_count') or 0), int(result.get('warning_count') or 0),
            result.get('context_sha256'), context_path or result.get('context_path'), result_path or result.get('result_path'), source, bool(result.get('local_only', True)),
            bool(result.get('production_side_effect', False)), bool(result.get('secret_redacted', True)), _json_dumps(result), _json_dumps({'recorded_by': source}),
        ],
    )
    row = rows[0]
    guardrail_result_id = row['id']

    for check in result.get('results') or []:
        query_json(
            """
            INSERT INTO seo_os.guardrail_result_checks (
              guardrail_result_id, guardrail_id, status, severity, enforce_mode,
              failure_state, reason, missing_evidence, action_on_fail, evidence, check_json
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb)
            """,
            [
                guardrail_result_id,
                check.get('guardrail_id'),
                check.get('status'),
                check.get('severity'),
                check.get('enforce_mode'),
                check.get('failure_state'),
                check.get('reason'),
                _json_dumps(check.get('missing_evidence') or []),
                _json_dumps(check.get('action_on_fail') or []),
                _json_dumps(check.get('evidence') or {}),
                _json_dumps(check),
            ],
        )

    return {
        'ok': True,
        'guardrail_result_id': str(guardrail_result_id),
        'result_id': str(row['result_id']),
        'workflow_event_id': str(row['workflow_event_id']) if row.get('workflow_event_id') else None,
        'task_ref': row['task_ref'],
        'stage': row['stage'],
        'status': row['status'],
        'secret_redacted': True,
    }
