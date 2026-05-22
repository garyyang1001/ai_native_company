#!/usr/bin/env python3
"""Agent artifact contract helpers for SEO OS local autopilot.

Accepted agent output shapes:

1. JSON line/object in stdout:
   {"artifacts":[{"path":"/abs/file.md","type":"final_article","summary":"..."}]}
   {"artifact":{"path":"/abs/file.md","type":"audit_report"}}

2. Text markers in stdout:
   ARTIFACT: /abs/file.md type=final_article summary="final article"
   artifact_path: /abs/file.md

3. Manifest file:
   {"artifacts":[...]}

This module only parses local paths and metadata. It never writes Payload,
never deploys, and never reads secrets.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

ALLOWED_ARTIFACT_TYPES = {
    'research_report', 'research_summary', 'outline', 'outline_json', 'draft',
    'final_article', 'audit_report', 'patch_plan', 'fix_queue', 'link_audit',
    'performance_report', 'gsc_raw', 'competitor_snapshot', 'google_doc',
    'manifest', 'weekly_report', 'schema_json', 'migration_sql',
    'cms_draft_payload', 'cms_preview_snapshot', 'image_asset', 'brand_asset',
    'media_asset_plan', 'media_asset_report', 'priority_report', 'query_report',
    'video_brief', 'video_upload_record', 'video_asset', 'other',
}

STRICT_ARTIFACT_PROFILES = {
    'writer',
    'article-editor',
    'link-finder',
    'cms-draft-executor',
}

ARTIFACT_TYPE_POLICY: dict[tuple[str, str], dict[str, Any]] = {
    ('writer', 'write'): {'any_of': ['final_article']},
    ('writer', 'article_refresh'): {'any_of': ['final_article']},
    ('writer', 'refresh'): {'any_of': ['final_article']},
    ('article-editor', 'audit'): {'any_of': ['audit_report']},
    ('article-editor', 'pre_publish_audit'): {'any_of': ['audit_report']},
    ('article-editor', 'refresh'): {'any_of': ['audit_report', 'patch_plan', 'fix_queue']},
    ('article-editor', 'cms_patch_plan'): {'any_of': ['patch_plan']},
    ('article-editor', 'cannibalization_scan'): {'any_of': ['audit_report']},
    ('link-finder', 'link_fix'): {'any_of': ['link_audit']},
    ('link-finder', 'internal_link_fix'): {'any_of': ['link_audit']},
    ('cms-draft-executor', 'cms_draft'): {'any_of': ['cms_draft_payload', 'cms_preview_snapshot']},
    ('cms-draft-executor', 'published_content_correction'): {'any_of': ['cms_draft_payload', 'cms_preview_snapshot']},
    ('cms-draft-executor', 'publish'): {'any_of': ['cms_draft_payload', 'cms_preview_snapshot']},
    ('topic-researcher', 'research'): {'any_of': ['research_report', 'research_summary']},
    ('topic-researcher', 'new_article'): {'any_of': ['research_report', 'research_summary']},
    ('outline-planner', 'outline'): {'any_of': ['outline', 'outline_json']},
    ('outline-planner', 'new_article'): {'any_of': ['outline', 'outline_json']},
    ('media-asset-generator', 'media_asset'): {'any_of': ['image_asset', 'brand_asset', 'media_asset_plan', 'media_asset_report']},
    ('media-asset-generator', 'new_article'): {'any_of': ['image_asset', 'brand_asset', 'media_asset_plan', 'media_asset_report']},
    ('seo-graph', 'query'): {'any_of': ['query_report', 'manifest', 'priority_report']},
    ('seo-graph', 'cannibalization_scan'): {'any_of': ['query_report', 'manifest', 'priority_report']},
    ('seo-graph', 'performance_feedback'): {'any_of': ['performance_report', 'query_report', 'manifest']},
    ('video-producer', 'video_production'): {'any_of': ['video_upload_record', 'video_brief', 'manifest']},
    ('video-producer', 'video_produce'): {'any_of': ['video_upload_record', 'video_brief', 'manifest']},
    ('video-producer', 'video_replace'): {'any_of': ['video_upload_record', 'video_brief', 'manifest']},
}


def artifact_type_policy(profile: str | None, task_type: str | None) -> dict[str, Any]:
    profile = str(profile or '').strip()
    task_type = str(task_type or '').strip()
    spec = ARTIFACT_TYPE_POLICY.get((profile, task_type), {})
    expected = [normalize_type(item) for item in spec.get('any_of', []) if item]
    enforcement = 'strict' if profile in STRICT_ARTIFACT_PROFILES else 'warn'
    return {
        'profile': profile,
        'task_type': task_type,
        'expected_types': expected,
        'enforcement': enforcement if expected else 'none',
    }


def evaluate_artifact_type_policy(*, profile: str | None, task_type: str | None, contract: dict[str, Any]) -> dict[str, Any]:
    policy = artifact_type_policy(profile, task_type)
    artifacts = contract.get('artifacts') if isinstance(contract, dict) else []
    actual_types = sorted({
        normalize_type(item.get('type')) for item in artifacts
        if isinstance(item, dict) and item.get('type')
    })
    expected_types = policy.get('expected_types') or []
    matched_types = sorted(set(actual_types) & set(expected_types))
    ok = True if policy.get('enforcement') == 'none' else bool(matched_types)
    return {
        **policy,
        'ok': ok,
        'actual_types': actual_types,
        'matched_types': matched_types,
        'secret_redacted': True,
    }

_MARKER_RE = re.compile(r'(?im)^\s*(?:ARTIFACT|artifact_path)\s*:\s*(?P<path>\S+)(?P<rest>.*)$')
_TYPE_RE = re.compile(r'\btype=(?P<quote>["\']?)(?P<value>[a-zA-Z0-9_\-]+)(?P=quote)')
_SUMMARY_RE = re.compile(r'\bsummary=(?P<quote>["\'])(?P<value>.*?)(?P=quote)')


def normalize_type(value: str | None, default: str = 'other') -> str:
    if not value:
        return default
    cleaned = str(value).strip().replace('-', '_')
    return cleaned if cleaned in ALLOWED_ARTIFACT_TYPES else default


def infer_type_from_path(path: str | Path, default: str = 'other') -> str:
    name = Path(path).name.lower()
    if 'final' in name and 'article' in name:
        return 'final_article'
    if 'audit' in name:
        return 'audit_report'
    if 'patch' in name:
        return 'patch_plan'
    if 'fix' in name or 'queue' in name:
        return 'fix_queue'
    if 'outline' in name:
        return 'outline_json' if name.endswith('.json') else 'outline'
    if 'link' in name:
        return 'link_audit'
    if 'manifest' in name:
        return 'manifest'
    return default


def _coerce_artifact(raw: Any, *, default_type: str = 'other') -> dict[str, Any] | None:
    if isinstance(raw, str):
        raw = {'path': raw}
    if not isinstance(raw, dict):
        return None
    path = raw.get('path') or raw.get('artifact_path') or raw.get('file') or raw.get('local_path')
    if not path:
        return None
    artifact_type = normalize_type(raw.get('type') or raw.get('artifact_type'), infer_type_from_path(path, default_type))
    return {
        'path': str(path),
        'type': artifact_type,
        'summary': raw.get('summary') or raw.get('description'),
        'google_doc_url': raw.get('google_doc_url'),
        'url': raw.get('url'),
        'metadata': raw.get('metadata') if isinstance(raw.get('metadata'), dict) else {},
    }


def _extract_from_json_obj(obj: Any, *, default_type: str) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if isinstance(obj, dict):
        if 'artifacts' in obj and isinstance(obj['artifacts'], list):
            for item in obj['artifacts']:
                art = _coerce_artifact(item, default_type=default_type)
                if art:
                    found.append(art)
        for key in ('artifact', 'output', 'final_artifact'):
            if key in obj:
                art = _coerce_artifact(obj[key], default_type=default_type)
                if art:
                    found.append(art)
        if any(k in obj for k in ('path', 'artifact_path', 'file', 'local_path')):
            art = _coerce_artifact(obj, default_type=default_type)
            if art:
                found.append(art)
    elif isinstance(obj, list):
        for item in obj:
            found.extend(_extract_from_json_obj(item, default_type=default_type))
    return found


def artifacts_from_text(text: str, *, default_type: str = 'other') -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    stripped = text.strip()
    if stripped:
        # Try full stdout JSON first.
        try:
            found.extend(_extract_from_json_obj(json.loads(stripped), default_type=default_type))
        except Exception:
            pass
        # Then JSON lines.
        for line in stripped.splitlines():
            line = line.strip()
            if not line or not (line.startswith('{') or line.startswith('[')):
                continue
            try:
                found.extend(_extract_from_json_obj(json.loads(line), default_type=default_type))
            except Exception:
                continue
    for m in _MARKER_RE.finditer(text):
        path = m.group('path').strip().strip('"\'')
        rest = m.group('rest') or ''
        typem = _TYPE_RE.search(rest)
        summ = _SUMMARY_RE.search(rest)
        found.append({
            'path': path,
            'type': normalize_type(typem.group('value') if typem else None, infer_type_from_path(path, default_type)),
            'summary': summ.group('value') if summ else None,
            'metadata': {'source': 'stdout_marker'},
        })
    return dedupe_artifacts(found)


def artifacts_from_manifest(path: str | Path | None, *, default_type: str = 'other') -> list[dict[str, Any]]:
    if not path:
        return []
    p = Path(path)
    if not p.exists() or not p.is_file():
        return []
    try:
        obj = json.loads(p.read_text(encoding='utf-8'))
    except Exception:
        return []
    found = _extract_from_json_obj(obj, default_type=default_type)
    for item in found:
        item.setdefault('metadata', {})
        item['metadata']['manifest_path'] = str(p)
    return dedupe_artifacts(found)


def dedupe_artifacts(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in items:
        path = str(item.get('path') or '')
        if not path:
            continue
        typ = normalize_type(item.get('type'), infer_type_from_path(path))
        key = (path, typ)
        if key in seen:
            continue
        seen.add(key)
        clean = dict(item)
        clean['type'] = typ
        clean['path'] = path
        clean['metadata'] = clean.get('metadata') if isinstance(clean.get('metadata'), dict) else {}
        out.append(clean)
    return out


def build_contract(*, stdout_text: str = '', manifest_path: str | None = None, expected_output: str | None = None, artifact_type: str = 'other', artifact_summary: str | None = None) -> dict[str, Any]:
    artifacts: list[dict[str, Any]] = []
    if expected_output:
        artifacts.append({
            'path': expected_output,
            'type': normalize_type(artifact_type, infer_type_from_path(expected_output)),
            'summary': artifact_summary,
            'metadata': {'source': 'expected_output_arg'},
        })
    artifacts.extend(artifacts_from_manifest(manifest_path, default_type=artifact_type))
    artifacts.extend(artifacts_from_text(stdout_text or '', default_type=artifact_type))
    artifacts = dedupe_artifacts(artifacts)
    return {
        'ok': bool(artifacts),
        'artifacts': artifacts,
        'artifact_count': len(artifacts),
        'manifest_path': manifest_path,
        'secret_redacted': True,
    }
