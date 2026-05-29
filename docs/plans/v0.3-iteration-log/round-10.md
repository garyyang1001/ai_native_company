# Round 10 — Phase 7 patch emitter + AST guard

**Date**:2026-05-29
**Status**:Phase 7 ship complete
**Commit**:`c1d19d1`

---

## 1. 情境

Round 9 把人類審核線打通,候選通過 sandbox 後狀態變 `sandbox_verified`。但只是「實驗室數據說 OK」,沒有真實 source code 改動 — query_parser.py 還是 V0.2 原樣,bot 不會真學會。Round 10 補 Phase 7:把 `sandbox_verified` candidate 變成真 git commit on `wannavegtour/query_parser.py`。

## 2. 流程

```
sandbox_verified
        ↓ (Phase 7)
emit_for_candidate(candidate_id)
        ↓
read typed_payload.value
        ↓
emit_keyword_patch(source, keyword)  # ast-walk find _AVAILABILITY_KEYWORDS tuple, append element
        ↓
assert_patch_is_surgical(old, new, keyword)  # AST diff guard
        ├─ pass → write file → git commit (Co-Authored gemma4 + Approved-By <gary id>)
        │                          → status='patch_emitted' + event
        └─ fail → status='patch_too_invasive' + event with reason
```

## 3. 實作要點

- `emit_keyword_patch` 用 `ast.parse` 找 `_AVAILABILITY_KEYWORDS` Assign + Tuple value,然後 balance parens 從 tuple 起始 line 往前掃,定位 closing `)`,直接 textual insert(保留 indent + comment 一切原樣;不用 `ast.unparse` 因為它會 reformat)
- `assert_patch_is_surgical` 是 AST level 防呆:
  - module-level statement count 相同
  - 非 target node `ast.dump-eq`
  - target 還是 Assign → Tuple
  - new tuple.elts 長度 = old + 1
  - 前 N elts 完全相同
  - 第 N+1 elt 是 string Constant 且 = expected keyword
- 整段拒絕任何 control flow / new import / function body 改動 → 強制 surgical
- V0.3 simple:**只支援 availability_keyword**;availability_regex 直接 `patch_too_invasive`(理由:加新 module-level list + dispatch flow 改動 = AST guard 必 reject)
- `commit_patch` 用 deterministic author env(`OP Assistant gemma4 proposer`)+ co-author line for gemma4 + Approved-By for actor
- `emit_for_candidate` 查 latest `approvals` row 拿 approved_by 寫進 commit body

## 4. tests(13 cases)

- EmitKeywordPatchTests × 4 — 加 keyword 保留既有 / duplicate raises / missing target / non-tuple target
- AstGuardTests × 6 — happy / expected mismatch / extra statement / new import / existing changed / function body changed
- EmitForCandidateTests × 3 — missing / wrong_state(draft) / regex proposal too_invasive

## 5. production smoke test(safe)

```
python op_assistant_patch_emitter.py --candidate-id 3f356f63-1a3e-...
↓
{"status": "wrong_state", "candidate_status": "draft", "candidate_id": "..."}
```

Production candidate 是 draft → entrance check 拒,沒任何 mutation(source code 沒動,git tree clean)。

## 6. Karpathy lens

- **#1 Think Before Coding**:V0.3 simple 不開 regex patch — 強行加 list + dispatch flow 改動會 AST guard reject,認清這事就 simply skip + 標 `patch_too_invasive`,V0.4 再加
- **#2 Simplicity First**:用 textual edit 加 element 而非 ast.unparse 整檔 reformat
- **#3 Surgical Changes**:AST guard 強制只能 append 一 string,任何別的改動都 reject
- **#4 Goal-Driven Execution**:smoke test 證明 entrance check 守住 production,沒誤改 source

## 7. Round 11 計畫

- Phase 8 simple:apply(patch_emitted → applied + systemctl restart)+ kill(applied / patch_emitted → killed + git revert + restart)
- Dispatcher chain:Phase 6 → 7 → 8 整鏈起來,Telegram 按 ✅ 直到 bot 真的學會
- Telegram kill 按鈕真實 implement(目前只 audit-log)
