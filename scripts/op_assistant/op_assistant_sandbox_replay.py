"""V0.3 Phase 6 — sandbox replay engine.

Per `docs/contracts/op_assistant_v0.3/sandbox_protocol_v0.md`:

* Deterministic seed from candidate_id (sha256, masked to 63 bits so it
  fits PG BIGINT).
* Run id derived from candidate + seed + model digest + corpus snapshot
  hash + clock anchor — any drift in any of those yields a new id.
* FakeClock anchors every "now" reference so re-runs produce the same
  corpus window.
* Three corpus slices: 24-hour failures, 7-day successes, 30-day
  inbound. Each is loaded from the target database (production for real
  approved candidates, sandbox for the 1000-case sim).
* Four metrics — regression / improvement / ambiguity / over-greedy —
  with V0.3 honesty: only intent-level safety, not handler-quality.
* Single insert into `sandbox_runs` with ON CONFLICT (id) DO NOTHING so
  re-running with the same inputs is a no-op.

CLI::

    /home/wannavegtour/.hermes/hermes-agent/venv/bin/python \\
        scripts/op_assistant/op_assistant_sandbox_replay.py \\
        --candidate-id <UUID> \\
        [--target-db production|sandbox] \\
        [--clock-anchor 2026-05-29T09:00:00+00:00]

Code-is-Rule: no LLM is invoked here. gemma4's `model_digest` is recorded
but only as audit metadata; every routing decision is deterministic
Python.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Env + repo path
# ---------------------------------------------------------------------------

def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


def _load_env() -> None:
    profile = os.environ.get("HERMES_PROFILE", "op-assistant")
    _load_env_file(Path.home() / ".hermes" / "profiles" / profile / ".env")
    _load_env_file(Path.home() / ".hermes" / ".env")


REPO_PATH = os.environ.get(
    "WANNAVEGTOUR_REPO_PATH",
    "/home/wannavegtour/Desktop/AI Native Company/Gary",
)
if REPO_PATH not in sys.path:
    sys.path.insert(0, REPO_PATH)

from closed_loop_kernel.store import KernelStore, json_param  # noqa: E402

# ---------------------------------------------------------------------------
# Contract constants
# ---------------------------------------------------------------------------

SANDBOX_NS = uuid.UUID("a1b2c3d4-0000-0000-0000-000000000004")
QUERY_PARSER_PATH = Path(REPO_PATH) / "wannavegtour" / "query_parser.py"

PASS_REGRESSION_MAX = 0
PASS_IMPROVEMENT_MIN = 1
PASS_AMBIGUITY_MAX = 0
PASS_OVER_GREEDY_MAX = 0.50


# ---------------------------------------------------------------------------
# Deterministic primitives
# ---------------------------------------------------------------------------

@dataclass
class FakeClock:
    """Sandbox-only clock. The replay engine reads ``anchor`` as "now"
    and never calls ``datetime.now()`` directly so the same candidate +
    anchor pair always sees the same corpus window.
    """
    anchor: datetime
    tick_seconds: float = 0.0
    _offset: float = field(default=0.0, init=False)

    def now(self) -> datetime:
        t = self.anchor + timedelta(seconds=self._offset)
        self._offset += self.tick_seconds
        return t


def compute_seed(candidate_id: str) -> int:
    raw = int(hashlib.sha256(candidate_id.encode("utf-8")).hexdigest()[:16], 16)
    return raw & ((1 << 63) - 1)


def compute_corpus_snapshot_hash(corpus_rows: list[dict[str, Any]]) -> str:
    sorted_rows = sorted(corpus_rows, key=lambda r: str(r.get("id", "")))
    h = hashlib.sha256()
    for row in sorted_rows:
        h.update(str(row.get("id", "")).encode("utf-8"))
        h.update(b":")
        payload_value = row.get("payload", row.get("text", ""))
        if not isinstance(payload_value, (dict, list, str, int, float, type(None))):
            payload_value = str(payload_value)
        payload_canon = json.dumps(
            payload_value, sort_keys=True, ensure_ascii=False, default=str,
        ).encode("utf-8")
        h.update(hashlib.sha256(payload_canon).digest())
    return h.hexdigest()


def compute_run_id(candidate_id: str, seed: int, model_digest: str,
                    corpus_snapshot_hash: str,
                    clock_started_at: datetime) -> str:
    key = (
        f"{candidate_id}:{seed}:{model_digest}:"
        f"{corpus_snapshot_hash}:{clock_started_at.isoformat()}"
    )
    return str(uuid.uuid5(SANDBOX_NS, key))


def compute_model_digest(model_name: str) -> str:
    """sha256-truncated digest of the ollama modelfile. Falls back to
    hashing the model name when the API isn't reachable so we still get
    a deterministic value (just one that doesn't move with model
    upgrades — the run id will then need cache invalidation if the
    operator bumps the model).
    """
    try:
        import requests
        r = requests.post(
            "http://127.0.0.1:11434/api/show",
            json={"model": model_name},
            timeout=15,
        )
        if r.status_code == 200:
            data = r.json()
            modelfile = data.get("modelfile") or ""
            if modelfile:
                return hashlib.sha256(modelfile.encode("utf-8")).hexdigest()[:24]
    except Exception:
        pass
    return hashlib.sha256(model_name.encode("utf-8")).hexdigest()[:24]


# ---------------------------------------------------------------------------
# Parser loading (isolated copies + handle that supports keyword/regex extras
# without touching V0.2 query_parser.py source)
# ---------------------------------------------------------------------------

_parser_load_counter = 0


class _ParserHandle:
    """Uniform wrapper exposing ``parse_query(text, today=None)`` for both
    the original parser and any patched variant. Keyword extras get
    monkey-patched into the isolated module's ``_AVAILABILITY_KEYWORDS``;
    regex extras are checked **after** the original parser returns
    ``unclear`` so we don't break V0.2's date-pattern assumption that
    every regex has two capture groups.
    """

    def __init__(self, module, regex_extras: list[str]) -> None:
        self._mod = module
        self._regex_extras = [re.compile(p) for p in regex_extras]

    def parse_query(self, text: str, today=None):
        result = self._mod.parse_query(text, today=today)
        if result.intent.value != "unclear" or not self._regex_extras:
            return result
        for rx in self._regex_extras:
            if rx.search(text):
                # The V0.2 parser is single-intent; substitute the intent
                # while keeping the rest of ParsedQuery intact.
                from dataclasses import replace
                return replace(
                    result, intent=self._mod.QueryIntent.AVAILABILITY_CHECK,
                )
        return result


def load_query_parser(extras: list[tuple[str, str]] | None = None) -> _ParserHandle:
    """Return a ``_ParserHandle`` wrapping a fresh isolated
    ``query_parser`` module. ``extras`` is an ordered list of
    ``(kind, value)`` tuples; ``kind`` is ``'keyword'`` (appended to
    ``_AVAILABILITY_KEYWORDS``) or ``'regex'`` (checked in the handle
    after the original parser yields unclear).
    """
    global _parser_load_counter
    _parser_load_counter += 1
    module_name = f"query_parser_isolated_{_parser_load_counter}"
    spec = importlib.util.spec_from_file_location(
        module_name, str(QUERY_PARSER_PATH),
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # dataclass decorator introspects sys.modules[cls.__module__] to detect
    # KW_ONLY etc; register before exec so the @dataclass lines work.
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(module_name, None)
        raise

    regex_extras: list[str] = []
    if extras:
        for kind, value in extras:
            if kind == "keyword":
                module._AVAILABILITY_KEYWORDS = (
                    *module._AVAILABILITY_KEYWORDS, value,
                )
            elif kind == "regex":
                regex_extras.append(value)
            else:
                raise ValueError(f"unsupported extras kind: {kind!r}")
    return _ParserHandle(module, regex_extras)


# ---------------------------------------------------------------------------
# Corpus loading
# ---------------------------------------------------------------------------

def load_corpus(store: KernelStore, clock: FakeClock) -> dict[str, list[dict]]:
    now = clock.now()
    cutoff_24h = (now - timedelta(hours=24)).isoformat()
    cutoff_7d = (now - timedelta(days=7)).isoformat()
    cutoff_30d = (now - timedelta(days=30)).isoformat()

    failures_24h = store.fetch_all(
        "SELECT f.id::text AS id, f.context AS payload "
        "FROM failures f WHERE f.created_at >= ? "
        "ORDER BY f.created_at",
        [cutoff_24h],
    )
    success_7d = store.fetch_all(
        "SELECT a.id::text AS id, ae.machine_record AS payload "
        "FROM attempt_envelopes ae JOIN attempts a ON a.id = ae.attempt_id "
        "WHERE a.created_at >= ? "
        "ORDER BY a.created_at",
        [cutoff_7d],
    )
    inbound_30d = store.fetch_all(
        "SELECT e.id::text AS id, e.payload AS payload "
        "FROM events e WHERE e.event_type = 'op_assistant_line_inbound' "
        "AND e.created_at >= ? "
        "ORDER BY e.created_at",
        [cutoff_30d],
    )
    return {
        "failures_24h": failures_24h,
        "success_7d": success_7d,
        "inbound_30d": inbound_30d,
    }


def extract_text(row: dict[str, Any]) -> str:
    """The three corpus slices stash their text at different JSON paths.
    failures.context.message_preview_redacted; attempt_envelopes
    .machine_record.message_preview_redacted; events.payload.text.
    """
    payload = row.get("payload") or {}
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except Exception:
            return payload
    if not isinstance(payload, dict):
        return ""
    text = (
        payload.get("message_preview_redacted")
        or payload.get("text")
        or ""
    )
    return text.strip() if isinstance(text, str) else ""


# ---------------------------------------------------------------------------
# Metric calculation
# ---------------------------------------------------------------------------

def compute_metrics(corpus: dict[str, list[dict]],
                     original_parser, patched_parser) -> dict[str, Any]:
    failures_24h = corpus["failures_24h"]
    success_7d = corpus["success_7d"]
    inbound_30d = corpus["inbound_30d"]

    # 1. regression — a 7-day-success row that originally produced a
    #    non-unclear intent must keep the same intent under the patch.
    regression_count = 0
    for row in success_7d:
        text = extract_text(row)
        if not text:
            continue
        orig = original_parser.parse_query(text).intent.value
        if orig == "unclear":
            continue
        patch = patched_parser.parse_query(text).intent.value
        if orig != patch:
            regression_count += 1

    # 2. improvement — a 24-hour-failure row that was unclear should now
    #    be parsed non-unclear under the patch.
    improvement_count = 0
    for row in failures_24h:
        text = extract_text(row)
        if not text:
            continue
        orig = original_parser.parse_query(text).intent.value
        patch = patched_parser.parse_query(text).intent.value
        if orig == "unclear" and patch != "unclear":
            improvement_count += 1

    # 3. ambiguity — V0.3 parser is single-intent so this is always 0;
    #    placeholder for V0.4 multi-intent dispatch.
    ambiguity_count = 0

    # 4. over-greedy — fraction of 30-day-inbound originally-unclear rows
    #    that the patch now matches. High means the new rule is grabbing
    #    too much of the unclear corpus.
    unclear_total = 0
    newly_matched = 0
    for row in inbound_30d:
        text = extract_text(row)
        if not text:
            continue
        orig = original_parser.parse_query(text).intent.value
        if orig != "unclear":
            continue
        unclear_total += 1
        patch = patched_parser.parse_query(text).intent.value
        if patch != "unclear":
            newly_matched += 1
    over_greedy_rate = (
        newly_matched / unclear_total if unclear_total > 0 else 0.0
    )

    return {
        "regression_count": regression_count,
        "improvement_count": improvement_count,
        "ambiguity_count": ambiguity_count,
        "over_greedy_rate": round(over_greedy_rate, 4),
        "corpus_24h_size": len(failures_24h),
        "corpus_7d_size": len(success_7d),
        "corpus_30d_size": len(inbound_30d),
        "corpus_30d_unclear_size": unclear_total,
        "newly_matched_unclear": newly_matched,
    }


def evaluate_pass(metrics: dict[str, Any]) -> tuple[str, str | None]:
    if metrics["regression_count"] > PASS_REGRESSION_MAX:
        return "failed", "regression_count_nonzero"
    if metrics["improvement_count"] < PASS_IMPROVEMENT_MIN:
        return "failed", "improvement_count_below_threshold"
    if metrics["ambiguity_count"] > PASS_AMBIGUITY_MAX:
        return "failed", "ambiguity_count_nonzero"
    if metrics["over_greedy_rate"] >= PASS_OVER_GREEDY_MAX:
        return "failed", "over_greedy_rate_above_threshold"
    return "passed", None


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def run_sandbox_replay(*,
                        candidate_id: str,
                        target_db_url: str,
                        clock_anchor: datetime | None = None,
                        model_name: str = "gemma4:e4b") -> dict[str, Any]:
    store = KernelStore.from_url(target_db_url)
    try:
        cand = store.fetch_one(
            "SELECT id::text AS id, proposal_type, typed_payload, status "
            "FROM improvement_candidates WHERE id = ?",
            [candidate_id],
        )
        if cand is None:
            raise RuntimeError(f"unknown candidate {candidate_id}")
        if cand["proposal_type"] not in (
            "availability_keyword", "availability_regex",
        ):
            raise RuntimeError(
                f"unsupported proposal_type {cand['proposal_type']!r} "
                f"for sandbox replay"
            )

        seed = compute_seed(candidate_id)
        anchor = clock_anchor or datetime.now(timezone.utc)
        clock = FakeClock(anchor=anchor)
        model_digest = compute_model_digest(model_name)

        corpus = load_corpus(store, clock)
        all_rows = (
            corpus["failures_24h"]
            + corpus["success_7d"]
            + corpus["inbound_30d"]
        )
        corpus_size = len(all_rows)
        corpus_snapshot_hash = compute_corpus_snapshot_hash(all_rows)
        run_id = compute_run_id(
            candidate_id, seed, model_digest, corpus_snapshot_hash, anchor,
        )

        typed_payload = cand["typed_payload"]
        if isinstance(typed_payload, str):
            typed_payload = json.loads(typed_payload)
        value = typed_payload["value"]

        original_parser = load_query_parser()
        extras_kind = (
            "keyword" if cand["proposal_type"] == "availability_keyword"
            else "regex"
        )
        patched_parser = load_query_parser(extras=[(extras_kind, value)])

        t_start = time.monotonic()
        metrics = compute_metrics(corpus, original_parser, patched_parser)
        duration_ms = int((time.monotonic() - t_start) * 1000)

        status, fail_reason = evaluate_pass(metrics)
        metrics["corpus_snapshot_hash"] = corpus_snapshot_hash

        completed_at = datetime.now(timezone.utc).isoformat()
        store.execute(
            "INSERT INTO sandbox_runs ("
            "id, candidate_id, seed, corpus_size, corpus_snapshot_hash, "
            "clock_started_at, model_digest, metrics, status, fail_reason, "
            "duration_ms, completed_at"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT (id) DO NOTHING",
            [
                run_id, candidate_id, seed, corpus_size,
                corpus_snapshot_hash, anchor.isoformat(), model_digest,
                json_param(metrics), status, fail_reason, duration_ms,
                completed_at,
            ],
        )

        return {
            "run_id": run_id,
            "status": status,
            "fail_reason": fail_reason,
            "metrics": metrics,
            "duration_ms": duration_ms,
            "model_digest": model_digest,
            "corpus_snapshot_hash": corpus_snapshot_hash,
            "candidate_status_before": cand["status"],
        }
    finally:
        store.close()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _resolve_db_url(target_db: str) -> str:
    base = os.environ["KERNEL_DATABASE_URL"]
    if target_db == "sandbox":
        return base.replace(
            "op_assistant_kernel", "op_assistant_sandbox_kernel",
        )
    return base


def _parse_clock_anchor(s: str | None) -> datetime | None:
    if s is None:
        return None
    return datetime.fromisoformat(s)


def main() -> int:
    _load_env()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-id", required=True)
    parser.add_argument(
        "--target-db", choices=("production", "sandbox"),
        default="production",
    )
    parser.add_argument(
        "--clock-anchor", default=None,
        help="ISO8601 timestamp; defaults to wall-clock now",
    )
    parser.add_argument("--model", default="gemma4:e4b")
    args = parser.parse_args()

    result = run_sandbox_replay(
        candidate_id=args.candidate_id,
        target_db_url=_resolve_db_url(args.target_db),
        clock_anchor=_parse_clock_anchor(args.clock_anchor),
        model_name=args.model,
    )
    print(json.dumps({
        "run_id": result["run_id"],
        "status": result["status"],
        "fail_reason": result["fail_reason"],
        "metrics": result["metrics"],
        "duration_ms": result["duration_ms"],
        "model_digest": result["model_digest"],
    }, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
