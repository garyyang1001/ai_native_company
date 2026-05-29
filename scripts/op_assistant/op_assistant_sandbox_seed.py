"""V0.3 Round 12 — seed the sandbox DB with 1000 simulated OP-group inbound.

The shape is per ``round-06.md`` Q2 + ``sandbox_protocol_v0.md``:

* gemma4 (called once, result cached in
  ``scripts/op_assistant/sandbox_seed_corpus.json``) distills the
  real 24-row production inbound into 80-120 phrasing seeds.
* Python template/slot expander deterministically blows those seeds
  out to 1000 inbound rows under a fixed ``--seed`` argument so the
  same seed always produces the same corpus.
* Distribution: 70% normal / 20% fuzzy-should-fail / 10% edge or
  malicious (codex Round 6 Q2 recommendation).
* Rows are inserted into ``op_assistant_sandbox_kernel`` as
  ``events.op_assistant_line_inbound`` so Phase 6 replay corpus sees
  them; we also fabricate matching ``failures`` rows for the
  fuzzy-fail subset so Phase 6's improvement metric has something to
  measure.

No production database is touched. PII anonymisation is irrelevant
here because the rows are LLM-generated, not copied from production
LINE — but we still hash a deterministic ``user_id`` per seed to
keep the row shape compatible with V0.2's parser.

Code-is-Rule: the only LLM call is the one-shot seed-generation
prompt at the top, gated behind a json cache file. Everything that
turns seeds into 1000 rows is pure deterministic Python.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

REPO_PATH = os.environ.get(
    "WANNAVEGTOUR_REPO_PATH",
    "/home/wannavegtour/Desktop/AI Native Company/Gary",
)
if REPO_PATH not in sys.path:
    sys.path.insert(0, REPO_PATH)

from closed_loop_kernel.store import KernelStore, json_param  # noqa: E402

SEED_CORPUS_CACHE = Path(REPO_PATH) / "scripts" / "op_assistant" / "sandbox_seed_corpus.json"


# ---------------------------------------------------------------------------
# Seed generation (LLM-once, then deterministic)
# ---------------------------------------------------------------------------

DEFAULT_SEEDS = {
    # If gemma4 is unreachable we fall back to a hard-coded seed list so
    # the simulator still runs deterministically in CI / offline.
    "normal": [
        "{date} {destination} 還有空位嗎",
        "{date} {destination} 那團剩多少位",
        "{destination} {date} 還能報名嗎",
        "{destination} 行程介紹一下",
        "{date} 國內團還有哪些",
        "{date} 那團還收嗎",
        "{destination} {date} 多少錢",
        "{date} {destination} 還有沒有賣完",
    ],
    "fuzzy": [
        "下個月有沒有適合帶長輩的團",
        "最近哪一團性價比最高",
        "想找個輕鬆的行程",
        "推薦親子團",
        "想找小團",
    ],
    "edge": [
        "",
        "                ",
        "1' OR '1'='1",
        "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
        "🦄🌈🎉",
        "test\n\n\n\nmultiline",
    ],
}

DESTINATIONS = [
    "越南峴港", "日本九州", "韓國首爾", "泰國曼谷", "馬來西亞",
    "新加坡", "土耳其", "義大利", "瑞士", "土耳其", "希臘", "捷克",
    "京都", "沖繩", "北海道", "東京", "大阪", "釜山",
]


def _build_seed_prompt(real_inbound: list[str]) -> str:
    head = (
        "你是阿玩旅遊 OP 同事。下面是真實 OP-LINE 群裡同事問 bot 的"
        "問句樣本。請依同樣語氣 / 同樣領域,給我 100 條同類型問句,"
        "覆蓋三種風格:"
        "(A) 70% 正常查詢(有日期 + 地點 + 動詞)、"
        "(B) 20% 模糊應該失敗(沒日期、需要 bot 反問)、"
        "(C) 10% 邊界(超長、貼圖、SQL 注入嘗試、中英台混雜)。"
        "輸出 JSON,key 為 normal / fuzzy / edge,各為字串陣列。"
        "正常類請保留 {date} / {destination} 兩個 placeholder,"
        "我會用 Python 套版。"
    )
    body = "\n".join(f"- {row}" for row in real_inbound[:24])
    return f"{head}\n\n真實樣本:\n{body}\n\nJSON 輸出:"


def fetch_seeds(model_endpoint: str = "http://127.0.0.1:11434/v1/chat/completions",
                 model_name: str = "gemma4:e4b",
                 force_refresh: bool = False,
                 real_inbound: list[str] | None = None) -> dict[str, list[str]]:
    """Return a {normal, fuzzy, edge} seed dict. Cached after first call."""
    if SEED_CORPUS_CACHE.exists() and not force_refresh:
        try:
            data = json.loads(SEED_CORPUS_CACHE.read_text(encoding="utf-8"))
            if all(k in data for k in ("normal", "fuzzy", "edge")):
                return data
        except Exception:
            pass

    real_inbound = real_inbound or []
    if not real_inbound:
        # Without real samples or LLM access, use the hard-coded fallback.
        SEED_CORPUS_CACHE.write_text(
            json.dumps(DEFAULT_SEEDS, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return DEFAULT_SEEDS

    try:
        import requests
        prompt = _build_seed_prompt(real_inbound)
        resp = requests.post(
            model_endpoint,
            json={
                "model": model_name,
                "messages": [{"role": "user", "content": prompt}],
                "response_format": {"type": "json_object"},
                "temperature": 0.4,
            },
            timeout=180,
        )
        resp.raise_for_status()
        raw = resp.json()["choices"][0]["message"]["content"]
        seeds = json.loads(raw)
        for k in ("normal", "fuzzy", "edge"):
            seeds.setdefault(k, DEFAULT_SEEDS[k])
        SEED_CORPUS_CACHE.write_text(
            json.dumps(seeds, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return seeds
    except Exception:
        return DEFAULT_SEEDS


# ---------------------------------------------------------------------------
# Deterministic template expansion
# ---------------------------------------------------------------------------

def _format_date(rng: random.Random) -> str:
    fmt = rng.choice(["{m}/{d}", "{m}月{d}日", "{m}月{d}", "{m}-{d}"])
    m = rng.randint(1, 12)
    d = rng.randint(1, 28)
    return fmt.format(m=m, d=d)


def expand_inbound(seeds: dict[str, list[str]], n: int,
                    base_seed: int) -> list[dict[str, Any]]:
    """Produce ``n`` inbound rows deterministically from ``seeds`` + base_seed."""
    rng = random.Random(base_seed)
    target_normal = int(n * 0.70)
    target_fuzzy = int(n * 0.20)
    target_edge = n - target_normal - target_fuzzy

    rows: list[dict[str, Any]] = []
    for i in range(target_normal):
        tpl = rng.choice(seeds.get("normal") or DEFAULT_SEEDS["normal"])
        text = tpl.format(
            date=_format_date(rng),
            destination=rng.choice(DESTINATIONS),
        )
        rows.append({"text": text, "category": "normal", "index": i})
    for i in range(target_fuzzy):
        text = rng.choice(seeds.get("fuzzy") or DEFAULT_SEEDS["fuzzy"])
        rows.append({"text": text, "category": "fuzzy", "index": target_normal + i})
    for i in range(target_edge):
        text = rng.choice(seeds.get("edge") or DEFAULT_SEEDS["edge"])
        rows.append({"text": text,
                      "category": "edge",
                      "index": target_normal + target_fuzzy + i})
    rng.shuffle(rows)
    return rows


# ---------------------------------------------------------------------------
# Insert into sandbox DB
# ---------------------------------------------------------------------------

INBOUND_NS = uuid.UUID("a1b2c3d4-0000-0000-0000-000000000005")
FAILURE_NS = uuid.UUID("a1b2c3d4-0000-0000-0000-000000000006")
ATTEMPT_NS = uuid.UUID("a1b2c3d4-0000-0000-0000-000000000007")


def _stable_uuid(namespace: uuid.UUID, key: str) -> str:
    return str(uuid.uuid5(namespace, key))


def _fake_user_id(seed: int, idx: int) -> str:
    return "U" + hashlib.sha256(f"{seed}:{idx}".encode("utf-8")).hexdigest()[:32]


def seed_sandbox(target_db_url: str, *, n: int, base_seed: int,
                  clock_anchor: datetime | None = None,
                  real_inbound: list[str] | None = None) -> dict[str, Any]:
    seeds = fetch_seeds(real_inbound=real_inbound)
    rows = expand_inbound(seeds, n, base_seed)
    clock = clock_anchor or datetime.now(timezone.utc)

    inbound_inserts = 0
    failure_inserts = 0
    skip_inserts = 0
    store = KernelStore.from_url(target_db_url)
    try:
        for offset, row in enumerate(rows):
            # Spread rows across the last 30 fake-clock days so Phase 6
            # corpus slices (24h failures, 7d success, 30d unclear) see
            # interesting distributions.
            row_time = (
                clock - timedelta(minutes=offset * 30)
            ).isoformat()
            inbound_id = _stable_uuid(INBOUND_NS, f"{base_seed}:{row['index']}")
            store.execute(
                "INSERT INTO events (id, event_type, payload, created_at) "
                "VALUES (?, ?, ?, ?) ON CONFLICT (id) DO NOTHING",
                [
                    inbound_id,
                    "op_assistant_line_inbound",
                    json_param({
                        "text": row["text"],
                        "user_id": _fake_user_id(base_seed, row["index"]),
                        "message_id": f"sim-{base_seed}-{row['index']}",
                        "category": row["category"],
                        "sim_seeded": True,
                    }),
                    row_time,
                ],
            )
            inbound_inserts += 1

            if row["category"] in ("fuzzy", "edge"):
                # Fabricate matching attempts + failures + attempt_envelopes
                # so Phase 6's 24h failures + 7d success slices have data.
                attempt_id = _stable_uuid(
                    ATTEMPT_NS, f"{base_seed}:{row['index']}:attempt"
                )
                store.execute(
                    "INSERT INTO attempts (id, event_id, status, input, "
                    "output, error_message, created_at) "
                    "VALUES (?, ?, 'failed', ?, NULL, ?, ?) "
                    "ON CONFLICT (id) DO NOTHING",
                    [
                        attempt_id,
                        inbound_id,
                        json_param({"text": row["text"]}),
                        "sim_unclear",
                        row_time,
                    ],
                )
                failure_id = _stable_uuid(
                    FAILURE_NS, f"{base_seed}:{row['index']}:failure"
                )
                store.execute(
                    "INSERT INTO failures (id, attempt_id, failure_type, "
                    "context, status, created_at) "
                    "VALUES (?, ?, 'outcome_failure', ?, 'open', ?) "
                    "ON CONFLICT (id) DO NOTHING",
                    [
                        failure_id,
                        attempt_id,
                        json_param({
                            "domain_failure_code": "missed_actionable_intent",
                            "trigger_reason": "parser_returned_unclear",
                            "message_preview_redacted": row["text"][:120],
                        }),
                        row_time,
                    ],
                )
                failure_inserts += 1
            else:
                # Normal rows get a success attempt_envelope so the 7-day
                # success regression corpus has something to compare.
                attempt_id = _stable_uuid(
                    ATTEMPT_NS, f"{base_seed}:{row['index']}:attempt"
                )
                envelope_id = _stable_uuid(
                    ATTEMPT_NS, f"{base_seed}:{row['index']}:envelope"
                )
                store.execute(
                    "INSERT INTO attempts (id, event_id, status, input, "
                    "output, created_at) VALUES "
                    "(?, ?, 'success', ?, ?, ?) "
                    "ON CONFLICT (id) DO NOTHING",
                    [
                        attempt_id, inbound_id,
                        json_param({"text": row["text"]}),
                        json_param({"intent": "availability_check"}),
                        row_time,
                    ],
                )
                store.execute(
                    "INSERT INTO attempt_envelopes ("
                    "id, attempt_id, task_id, run_id, profile_id, output_type,"
                    " machine_record, source_refs, confidence, "
                    "recommended_next_actions, verification_required, "
                    "review_required, retention_policy, content_hash, "
                    "created_at) VALUES "
                    "(?, ?, 'sim-task', 'sim-run', 'op-assistant-line', "
                    "'availability_reply', ?, ?, 'high', '[]'::jsonb, "
                    "FALSE, FALSE, '30d-events', ?, ?) "
                    "ON CONFLICT (id) DO NOTHING",
                    [
                        envelope_id, attempt_id,
                        json_param({
                            "parser_intent": "availability_check",
                            "message_preview_redacted": row["text"][:120],
                        }),
                        json_param([inbound_id]),
                        hashlib.sha256(row["text"].encode("utf-8")).hexdigest(),
                        row_time,
                    ],
                )
            # skip_inserts simply tracks edge rows where attempt creation
            # was skipped (none in this revision; reserved for future).

    finally:
        store.close()

    return {
        "inbound_inserts": inbound_inserts,
        "failure_inserts": failure_inserts,
        "skip_inserts": skip_inserts,
        "seed_cache": str(SEED_CORPUS_CACHE),
        "seed_distribution": {
            "normal": sum(1 for r in rows if r["category"] == "normal"),
            "fuzzy": sum(1 for r in rows if r["category"] == "fuzzy"),
            "edge": sum(1 for r in rows if r["category"] == "edge"),
        },
    }


def _load_env() -> None:
    profile = os.environ.get("HERMES_PROFILE", "op-assistant")
    for path in [
        Path.home() / ".hermes" / "profiles" / profile / ".env",
        Path.home() / ".hermes" / ".env",
    ]:
        if not path.exists():
            continue
        for raw in path.read_text().splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            os.environ.setdefault(key.strip(),
                                   val.strip().strip('"').strip("'"))


def main() -> int:
    _load_env()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--n", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--target-db", default=None,
                         help="sandbox DSN; defaults to swapping the production "
                              "KERNEL_DATABASE_URL DB name to "
                              "op_assistant_sandbox_kernel")
    parser.add_argument("--force-refresh-seeds", action="store_true")
    parser.add_argument("--clock-anchor", default=None)
    args = parser.parse_args()

    if args.target_db:
        target = args.target_db
    else:
        target = os.environ["KERNEL_DATABASE_URL"].replace(
            "op_assistant_kernel", "op_assistant_sandbox_kernel",
        )

    if args.force_refresh_seeds and SEED_CORPUS_CACHE.exists():
        SEED_CORPUS_CACHE.unlink()

    clock = None
    if args.clock_anchor:
        clock = datetime.fromisoformat(args.clock_anchor)

    result = seed_sandbox(
        target_db_url=target, n=args.n, base_seed=args.seed,
        clock_anchor=clock,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
