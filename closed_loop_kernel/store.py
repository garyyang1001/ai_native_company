from __future__ import annotations

import json
import re
import threading
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable

from .postgres import render_postgres_schema

RESET_CONFIRMATION = "drop-public-schema"


class KernelStore:
    def __init__(self, conn):
        self.conn = conn
        self._lock = threading.RLock()

    @classmethod
    def from_url(cls, url: str) -> "KernelStore":
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ModuleNotFoundError as exc:
            raise RuntimeError("KernelStore requires the optional 'psycopg' package") from exc
        return cls(psycopg.connect(url, row_factory=dict_row))

    def initialize(self) -> None:
        with self._lock:
            self.conn.execute(render_postgres_schema())
            self.conn.commit()

    def reset_for_test(self, *, confirm: str = "") -> None:
        if confirm != RESET_CONFIRMATION:
            raise RuntimeError("reset_for_test requires explicit destructive reset confirmation")
        with self._lock:
            self.conn.execute("DROP SCHEMA IF EXISTS public CASCADE; CREATE SCHEMA public;")
            self.conn.commit()

    def close(self) -> None:
        with self._lock:
            self.conn.close()

    def execute(self, sql: str, params: Iterable[Any] | None = None) -> None:
        with self._lock:
            self.conn.execute(_postgres_sql(sql), _postgres_params(params))
            self.conn.commit()

    def fetch_all(self, sql: str, params: Iterable[Any] | None = None) -> list[dict[str, Any]]:
        with self._lock:
            rows = self.conn.execute(_postgres_sql(sql), _postgres_params(params)).fetchall()
            # psycopg autocommit=False 下，read 仍會隱式啟動一筆 TX；
            # 不關掉，連線會停在 "idle in transaction"，阻擋後續 DDL（例如 reset 的
            # DROP SCHEMA），多用幾個連線就鎖住。explicit commit 沒副作用且必要。
            self.conn.commit()
        return [_normalize_row(row) for row in rows]

    def fetch_one(self, sql: str, params: Iterable[Any] | None = None) -> dict[str, Any] | None:
        with self._lock:
            row = self.conn.execute(_postgres_sql(sql), _postgres_params(params)).fetchone()
            self.conn.commit()
        return _normalize_row(row) if row else None

    def scalar(self, sql: str, params: Iterable[Any] | None = None) -> Any:
        with self._lock:
            row = self.conn.execute(_postgres_sql(sql), _postgres_params(params)).fetchone()
            self.conn.commit()
        if not row:
            return None
        if isinstance(row, dict):
            return _normalize_value(next(iter(row.values())))
        return _normalize_value(row[0])

    @contextmanager
    def transaction(self):
        with self._lock:
            tx = _PostgresTransaction(self.conn)
            try:
                yield tx
            except Exception:
                self.conn.rollback()
                raise
            else:
                self.conn.commit()


class _PostgresTransaction:
    def __init__(self, conn):
        self.conn = conn

    def execute(self, sql: str, params: Iterable[Any] | None = None):
        return self.conn.execute(_postgres_sql(sql), _postgres_params(params))


def _postgres_sql(sql: str) -> str:
    translated = _to_psycopg_placeholders(sql)
    translated = re.sub(r"\bis_active\s*=\s*1\b", "is_active = TRUE", translated)
    translated = re.sub(r"\bis_active\s*=\s*0\b", "is_active = FALSE", translated)
    return translated


def _postgres_params(params: Iterable[Any] | None) -> tuple[Any, ...]:
    return tuple(_postgres_param(param) for param in (params or ()))


def _postgres_param(param: Any) -> Any:
    if isinstance(param, JsonParam):
        parsed = json.loads(param.value)
        try:
            from psycopg.types.json import Json
        except ModuleNotFoundError:
            return parsed
        return Json(parsed)
    if not isinstance(param, str):
        return param
    return param


def _normalize_row(row) -> dict[str, Any]:
    return {key: _normalize_value(value) for key, value in dict(row).items()}


def _normalize_value(value: Any) -> Any:
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return value


def _to_psycopg_placeholders(sql: str) -> str:
    result = []
    in_single_quote = False
    in_double_quote = False
    escape_next = False

    for char in sql:
        if escape_next:
            result.append(char)
            escape_next = False
            continue
        if char == "\\":
            result.append(char)
            escape_next = True
            continue
        if char == "'" and not in_double_quote:
            in_single_quote = not in_single_quote
            result.append(char)
            continue
        if char == '"' and not in_single_quote:
            in_double_quote = not in_double_quote
            result.append(char)
            continue
        if char == "?" and not in_single_quote and not in_double_quote:
            result.append("%s")
            continue
        result.append(char)
    return "".join(result)


@dataclass(frozen=True)
class JsonParam:
    value: str


def json_param(value: Any) -> JsonParam:
    return JsonParam(json.dumps(value, ensure_ascii=False, sort_keys=True))
