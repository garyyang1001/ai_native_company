# Ohya Swarm Template — Existing Article Audit / Fix

用途：舊文 audit → graph suggestion → fix artifact → regression audit → CMS draft/correction gate。

## 建議任務圖

1. `article-editor` — audit target URL, output audit-report / patch-plan / fix-queue
2. `seo-graph` — read audit, suggest internal links / topic-cluster relationships
3. `writer` or `link-finder` — create corrected artifact, not production write
4. `article-editor` — regression audit corrected artifact
5. `cms-draft-executor` — draft/correction gate; no direct publish write

## Guardrails

- 對已 publish 的 Payload post，所有寫入都必須先變成 draft / correction plan。
- 若要更新 live published content，停等 Gary 明確 approval。
- 若找不到 Payload admin/JWT/session，不要猜；回報缺 auth。
