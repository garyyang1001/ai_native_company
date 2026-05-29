# Round 02 — 8 條 p0 spec collapse(codex 7 反提案全採納)

**Date**:2026-05-29
**Participants**:Claude Opus 4.7 ↔ codex `gpt-5.5 xhigh`
**Round 2 status**:collapsed — 8 條 spec final,Phase 2 開工 ready
**Result tone**:codex 罕見硬核 — 8 條 1 ✓ + 7 ✗ 反提案,全部合理我全收

---

## 1. Round 2 input

Claude 寫了 8 條 spec proposal 對 U34/U1/U2/U3/U37/U39/U10/U11(Round 1 收出的 attack list)。完整 prompt 在 `.claude/jobs/1d06a75b/round02_prompt.md`。

## 2. Round 2 codex output — 逐條結論(reviewed + accepted)

完整 codex output:`.claude/jobs/1d06a75b/round02_output.md`

### U34 — candidate lifecycle 狀態機 ✅(微調)

**Claude 原 spec**:11 states + Python module-level enum + PG CHECK + Python valid transition map。

**Codex 補**:狀態變更要另外留事件記錄,不能只改 row。

**Final spec**:
- `improvement_candidates.status` PG CHECK enum (11 states)
- Python `CandidateStatus(StrEnum)` + `_VALID_TRANSITIONS: dict[CandidateStatus, set[CandidateStatus]]`
- **新增** 每次 status update 同 transaction 寫 `events.candidate_status_changed`:`{candidate_id, from_status, to_status, by_phase, by_actor}`,append-only,可重建完整時間線

### U1 — payload_hash 演算法 ✅(改採 codex 反提案)

**Claude 原**:`SHA256(canonical(typed_payload only))`

**Codex 反提案**:漏 `proposal_type` 跟 `schema_version`,以後同 keyword 但不同 type 的 candidate 會撞 hash。

**Final spec**:
```python
def compute_payload_hash(proposal_type: str, typed_payload: dict,
                          schema_version: str = "v0.3.0") -> str:
    envelope = {
        "proposal_type": proposal_type,
        "schema_version": schema_version,
        "typed_payload": typed_payload,
    }
    canon = json.dumps(envelope, sort_keys=True,
                       ensure_ascii=False, separators=(',', ':'))
    return hashlib.sha256(canon.encode('utf-8')).hexdigest()
```

`callback_data` 格式 = `{action_short}:{candidate_id_short}:{hash_prefix}` 其中:
- `action_short` ∈ {apv, rej, vw, kill}(3-4 字)
- `candidate_id_short` = uuid base32 前 8 字
- `hash_prefix` = SHA256 前 8 字 hex
- 總長 ≤ 26 字,遠低於 64 byte 上限

### U2 — idempotency ✅(改採 codex 反提案)

**Claude 原**:`(source_event_id, proposal_index) UNIQUE`

**Codex 反提案**:`proposal_index` 綁 LLM 排序不穩;`--force` 偽造 `period_key` 污染時間語意。

**Final spec**:
```sql
ALTER TABLE improvement_candidates
  ADD COLUMN curation_run_id UUID NOT NULL,
  ADD COLUMN proposal_index INT NOT NULL,
  ADD CONSTRAINT candidates_run_proposal_unique
    UNIQUE (curation_run_id, proposal_index);
```

- `curation_run_id` = daily_curate 每次跑生一個新 uuid4(每次重跑是新 run,但 `period_key` 不變)
- `proposal_index` 是該 run 內 actionable list 的 index
- 同內容去重:額外用 `payload_hash` 做後驗(若同 payload_hash 已有 applied candidate → 不重複建 new candidate row,寫 `events.improvement_candidate_skipped` 註記)

### U3 — typed_payload schema enforcement ✅(改採 codex 反提案)

**Claude 原**:Python `assert` validator

**Codex 反提案**:`assert` 被 `python -O` 關掉(production 用 -O 不少);`re.compile()` 不防 catastrophic backtracking。

**Final spec**:
```python
class TypedPayloadError(ValueError):
    pass

_FORBIDDEN_KW_METACHARS = set(".^$*+?{}[]\\|()")
_MAX_KEYWORD_LEN = 50
_MAX_REGEX_LEN = 200
_FORBIDDEN_REGEX_PATTERNS = [
    r"(?:.+){2,}",     # nested quantifier (catastrophic backtracking)
    r"\(\?\:[^)]*\)\+", # (?:...) +
]

def validate_typed_payload(proposal_type: str, payload: dict) -> None:
    if proposal_type == "availability_keyword":
        kw = payload.get("keyword")
        if not isinstance(kw, str):
            raise TypedPayloadError("keyword must be str")
        if not (1 <= len(kw) <= _MAX_KEYWORD_LEN):
            raise TypedPayloadError(f"keyword len must be 1-{_MAX_KEYWORD_LEN}")
        forbidden = _FORBIDDEN_KW_METACHARS & set(kw)
        if forbidden:
            raise TypedPayloadError(f"keyword contains regex metachars: {forbidden}")
    elif proposal_type == "availability_regex":
        pat = payload.get("pattern")
        if not isinstance(pat, str):
            raise TypedPayloadError("pattern must be str")
        if not (1 <= len(pat) <= _MAX_REGEX_LEN):
            raise TypedPayloadError(f"pattern len must be 1-{_MAX_REGEX_LEN}")
        for forbidden in _FORBIDDEN_REGEX_PATTERNS:
            if re.search(forbidden, pat):
                raise TypedPayloadError(f"pattern matches forbidden form: {forbidden}")
        try:
            re.compile(pat)
        except re.error as exc:
            raise TypedPayloadError(f"pattern not compilable: {exc}") from None
    else:
        raise TypedPayloadError(f"unsupported proposal_type: {proposal_type}")
```

Future V0.4 評估 RE2(沒 catastrophic backtracking)取代 `re` 模組。

### U37 — generator_metadata pinning ✅(改採 codex 反提案)

**Claude 原**:`{model, prompt_version, prompt_hash, corpus_window_*, counts}`

**Codex 反提案**:只 hash 不存原文,Phase 6 replay 找不到當時 prompt 全文。

**Final spec**:
```python
generator_metadata = {
    "generator_name": "op_assistant_daily_curate",     # 哪個 generator 產的
    "generator_code_version": "<git sha>",              # daily_curate.py 當時 git sha
    "model": "gemma4:e4b",
    "model_params": {"temperature": 0.2, "response_format": "json_object"},
    "prompt_artifact_id": "<events.id of prompt-archive event>",  # 完整 prompt 存 events
    "prompt_version": "v0.3.1",                         # human-readable label
    "prompt_hash": "<sha256 of prompt text>",
    "schema_version": "v0.3.0",                         # typed_payload schema 版本
    "corpus_window_start_at": ISO8601,
    "corpus_window_end_at": ISO8601,
    "corpus_inbound_count": int,
    "corpus_failure_count": int,
}
```

- 完整 prompt 全文以 `events.daily_curate_prompt_archive` event 記錄(uuid5 idempotent by `prompt_hash`)
- candidate 引用 `prompt_artifact_id` → Phase 6 replay 真正能找回原 prompt

### U39 — observation→candidate trace ✅(改採 codex 反提案)

**Claude 原**:substring match keyword/pattern 在 message_preview → 加 `source_observation_ids JSONB`

**Codex 反提案**:substring 漏 regex case、漏 redacted preview;欄位名 ids 但塞 dict 不一致。

**Final spec**:
```sql
ALTER TABLE improvement_candidates
  ADD COLUMN candidate_sources JSONB NOT NULL DEFAULT '[]'::jsonb;
```

```python
# Each entry:
{
    "source_type": "failure",            # or "inbound_event" / "manual"
    "source_id": "<failures.id or events.id>",
    "inbound_event_id": "<events.op_assistant_line_inbound.id>",  # 上溯到原始
    "match_reason": "curated_failure",   # or "substring_match" / "manual_pin"
    "confidence": 1.0,                   # 1.0 for curated, <1.0 for heuristic
}
```

**優先取用 curated failures inbound link**(failures 表 attempt_id → attempt_envelopes → 原 events.inbound),而非靠 LLM 自己標、也不靠 substring match。Substring match 是 fallback,confidence 標 0.5。

→ **這也回應 codex assumption 2(failures → inbound stability):必須先確認 failures 表是否有穩定 inbound_event_id 鏈 → Round 3 spike**。

### U10 — actor × chat 雙重 allowlist ✅(改採 codex 反提案)

**Claude 原**:空 allowlist = 允許所有

**Codex 反提案**:批准權限要 fail-closed。空值允許所有違反 Code is Rule 信念。

**Final spec**:
- `TELEGRAM_ALLOWED_ACTORS` **production 必填**(plugin.yaml 標 `requires_env`,不是 optional_env)
- `ALLOW_ALL_TELEGRAM_ACTORS=true` 是 explicit dev escape hatch(plugin.yaml 標 dev-only,deploy 警告)
- Phase 4 dispatcher:`actor_user_id not in allowed_actors and not ALLOW_ALL_TELEGRAM_ACTORS` → audit + reply「您不在批准名單」+ 200 (不 403,因 chat 已過)

### U11 — transactional claim ✅(改採 codex 反提案)

**Claude 原**:`source_event_id UNIQUE` + INSERT-then-UPDATE

**Codex 反提案**:同 candidate 兩個不同 callback 競爭時 source_event_id UNIQUE 沒擋(兩個 event_id 都 unique)。

**Final spec(三層防護)**:
```sql
ALTER TABLE approvals
  ADD COLUMN source_event_id UUID,
  ADD COLUMN candidate_id UUID NOT NULL;

-- 防同 telegram_inbound 被處理兩次:
CREATE UNIQUE INDEX approvals_source_event_unique
  ON approvals (source_event_id) WHERE source_event_id IS NOT NULL;

-- 防同 candidate 多個 final decision(只允許一個 approve OR reject):
CREATE UNIQUE INDEX approvals_candidate_final_unique
  ON approvals (candidate_id) WHERE decision IN ('approved', 'rejected');
```

```python
def claim_and_apply(conn, event_id, candidate_id, expected_payload_hash, decision):
    # Layer 1: insert approval (claim event_id + candidate decision)
    row = conn.execute("""
        INSERT INTO approvals (id, candidate_id, source_event_id, decision, ...)
        VALUES (?, ?, ?, ?, ...)
        ON CONFLICT DO NOTHING
        RETURNING id
    """, [...]).fetchone()
    if row is None:
        return ClaimResult.ALREADY_CLAIMED
    
    # Layer 2: guarded update — candidate must still be in pushed state,
    # and payload_hash must match what user saw on the button.
    next_status = "approved" if decision == "approved" else "rejected"
    updated = conn.execute("""
        UPDATE improvement_candidates
        SET status = ?, updated_at = NOW()
        WHERE id = ?
          AND status = 'pushed_to_telegram'
          AND payload_hash = ?
        RETURNING id
    """, [next_status, candidate_id, expected_payload_hash]).fetchone()
    if updated is None:
        # candidate 已被別人處理 OR payload 已過期 → rollback
        conn.execute("ROLLBACK")
        return ClaimResult.STALE_OR_RACE
    return ClaimResult.OK
```

`expected_payload_hash` 從 callback_data 解 — 對應 R6 stale payload + 對應 codex 雙 callback 競爭風險。

## 3. Codex 提的 3 個 implicit assumption(Round 3 入口)

1. **callback_data 64 byte 格式** — U1 collapse 時順便 spec 了(`{action}:{candidate_id_short}:{hash_prefix}` ≤ 26 字)→ ✅
2. **failures → inbound event 穩定鏈** — U39 依賴。**Round 3 必 spike**:check `closed_loop_kernel/postgres.py` failures 表 schema、attempt_envelopes.source_refs JSON、events.op_assistant_line_inbound id 三者間的 link 是否穩
3. **狀態 transition 多 writer guarded update** — U11 三層防護已實作 → ✅

## 4. V0.3 doc 將要 patch 的部分

Round 2 結算這個 commit 把以下進 V0.3 design doc:

1. **§ TL;DR / 開頭**:加 codex Round 1 那句 framing「V0.3 不是『AI 自動改規則』,是『AI 提案,人批准,系統可重播、可驗證、可回滾』」
2. **Phase 2 spec**:用 Round 2 final 8 條完整 spec 取代當前粗描述
3. **§9 risk register**:加 R17(reviewer separation,U35)+ R18(failures→inbound link 未驗,Round 3 spike)
4. **§11 諮詢痕跡**:加 2026-05-29 Round 1 + Round 2 條目

## 5. Round 3 plan

Round 3 攻:
1. **Phase 2 開工 brief 寫**(基於本 round 8 條 spec + codex 反提案)
2. **spike failures→inbound stability**(讀 closed_loop_kernel/postgres.py + 採樣現有 failures 看 chain)
3. **U35 reviewer separation rule** 寫進 V0.3 doc(原則文字 + 對 Phase 6/7/8 的 enforcement 點)
4. **預備 Round 4 攻 U6/U7/U9 callback_data + KILL scope + message granularity**(Phase 3 開工前)

## 6. Karpathy lens

- **#1 Think Before Coding**:Round 2 把我 silently 假設「assert OK / hash typed_payload OK / index 綁 LLM 排序 OK」全部 surfaced。codex 7 反提案 100% take rate(我自己沒想到那麼深)。
- **#2 Simplicity First**:我考慮過 RE2 直接導入,但 codex 建議「V0.3 用 forbidden pattern blacklist,V0.4 再評 RE2」是更 simple 的階段切割。
- **#3 Surgical Changes**:這個 commit 動 round-02.md log + V0.3 doc patch(8 條 + framing + R17 R18 + §11),不動 schema migration / Python code(留 Phase 2 brief 起跑時動)。
- **#4 Goal-Driven Execution**:Round 2 success criteria = 8 條 final spec ✓,Phase 2 開工 ready ✓。

## 7. Artifacts

- Round 2 prompt:`.claude/jobs/1d06a75b/round02_prompt.md`
- Round 2 codex output:`.claude/jobs/1d06a75b/round02_output.md`
- 7 反提案全採納(history `codex session bw7t3p4p5`)
