# OP Kernel C1-C4 Execution Report — 2026-05-26

**Status**: ALL GREEN ✅
**Total wall time**: ~14 min(C1 3:11 + C2 2:51 + C3∥C4 6:47)
**Companion to**: `2026-05-26-op-kernel-codex-execute-plan.md`(4 brief 原文)
**Production impact**: NONE — `wannavegtourcrm-*` 7 個 container 全程沒被動,8765 標準聽器 / hermes-gateway.service / Tailscale Funnel 都 intact

## 結果速覽

| Phase | Codex agent | 耗時 | 結果 | Claude 驗證 |
|---|---|---|---|---|
| C1 | infrastructure | 3:11 min | ✅(psql client 沒裝,不擋) | ✅ container healthy / 5434 bind / CRM 7 個沒動 |
| C2 | schema + env | 2:51 min | ✅ 14 表 + 6 trigger | ✅ 表名全列 + trigger 全 attach 對 |
| C3 | cron scripts | ~6 min | ✅ 4 .py + 4 cron 註冊 + ETL smoke ok | ✅ chmod 700 / cron next-run 對 / events 表 0 row(正常) |
| C4 | backup | ~1 min | ✅ backup.sh + 3 crontab + 第 1 個 daily backup 寫成 | ✅ 3006 bytes 空 DB dump / 3 條 crontab on |

## 14 表(verified)

```
agents / approval_routes / approvals / artifacts / attempt_lifecycle_events /
attempts / decisions / events / failures / improvement_candidates /
policy_gates / replays / teams / tool_calls
```

## 6 prevent_mutation triggers(verified)

```
trg_protect_approvals / trg_protect_attempt_lifecycle_events /
trg_protect_attempts / trg_protect_decisions / trg_protect_events /
trg_protect_tool_calls
```

## 4 Hermes cron jobs(verified `hermes -p op-assistant cron list`)

| ID | name | schedule | next | last run | mode |
|---|---|---|---|---|---|
| e3b50014eeaa | op-etl | `0 */4 * * *` | 16:00 | 15:35:15 ok | no-agent |
| 661543fa5db0 | op-daily-curate | `0 9 * * *` | tomorrow 09:00 | — | no-agent |
| (略) | op-weekly-report | `0 9 * * 1` | next Monday 09:00 | — | no-agent |
| (略) | op-monthly-maint | `0 5 1 * *` | next month 1st 05:00 | — | no-agent |

## 3 backup crontab entries(verified `crontab -l`)

```
0 2 * * *     bash ~/.hermes/credentials/wannavegtour/op_kernel/backup.sh daily
30 2 * * 0    bash ~/.hermes/credentials/wannavegtour/op_kernel/backup.sh weekly
0 3 1 * *     bash ~/.hermes/credentials/wannavegtour/op_kernel/backup.sh monthly
```

## 護線基線檢查(每階段都驗,7 個 container 全 Up 17h+)

```
wannavegtourcrm-backend-1          Up 17 hours (no change)
wannavegtourcrm-frontend-1         Up 17 hours (no change)
wannavegtourcrm-admin-1            Up 17 hours (no change)
wannavegtourcrm-postgres-audit-1   Up 17 hours healthy (no change)
wannavegtourcrm-redis-1            Up 17 hours healthy (no change)
ohya-neo4j                         Up 17 hours healthy (no change)
open-webui                         Up 17 hours healthy (no change)
```

新多了:
```
op-assistant-kernel                Up 14 minutes healthy   127.0.0.1:5434
```

## C3 一個聰明 finding

`--no-agent` cron script 無 PYTHONPATH 指向 repo,Codex 自動建 symlink:
```
~/.hermes/profiles/op-assistant/scripts/closed_loop_kernel
  → /home/wannavegtour/Desktop/AI Native Company/Gary/closed_loop_kernel
```

hacky 但 works。**未來改成 `pip install -e` editable package 比較乾淨**。

## C1 一個小問題(不擋)

- `psql` client 沒裝。`sudo apt install postgresql-client` 需要 TTY/password,Codex non-interactive 過不了。
- 影響:Gary 之後手動 query op-assistant-kernel 不方便(必須 `docker exec` 跑 psql)
- Fix:`sudo apt install -y postgresql-client`(Gary 之後一個指令解決)

## 還沒做的事(下一階段)

| | 為什麼還沒做 |
|---|---|
| 6 個 Hermes tool 實作(query_intent / fetch_wc / compose / validate / send / escalate) | 還在 harness spec 階段(`docs/plans/2026-05-26-op-bot-hermes-harness-spec.md`),這次 deploy 只是「資料層 + cron」基礎建設 |
| SOUL.md 完整版 | 同上,等 6 tool 設計確定再寫 |
| MEMORY.md / USER.md seed | 同上 |
| LINE webhook 切到 Hermes:8646 | cutover 工作,等 6 tool 完成 + pre-launch test 過 |
| Tailscale Funnel 切 port | 同 cutover |
| 停舊 listener PID 49146 | 同 cutover |

## 接下來建議的路線

1. **codex review 跑一次本次 commit**(catch 任何 drift / 漏洞)
2. **手動 verify 一個 cron 跑得起來**(`hermes -p op-assistant cron run op-etl` 已驗 ok)
3. **設計 6 個 tool**(harness spec 已有大綱,需要 Gary 確認細節 — session_id 策略 / retry 行為 / escalate token 路徑)
4. **寫 3 個 replay script**(`replay_audit_to_kernel.py` / `replay_through_op_assistant.py` / `diff_replies.py`)
5. **6 tool 實作 + unit test + integration test**
6. **Pre-launch test:replay 過去 audit 跑新流程,出 test report**
7. **Cutover**(LINE webhook + Tailscale Funnel + 停舊 listener)
