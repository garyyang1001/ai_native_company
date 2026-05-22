# 好事發生數位 — SEO Multi-Agent System

好事發生數位 (ohya.co) 的 AI SEO 內容生產系統。

## 架構

- **平台**: Next.js + Payload CMS (Zeabur 託管)
- **Agent 框架**: Hermes Framework
- **知識圖譜**: Neo4j (bolt://localhost:7690)
- **溝通**: Telegram Bot → Coordinator → Subprocess Delegate

## Agent 清單

| Agent | 職責 |
|---|---|
| coordinator | 統一入口、派工、整合回報 |
| article-editor | 舊文診斷（6+1 檢查） |
| topic-researcher | SEO 主題研究 |
| outline-planner | 文章大綱規劃 |
| writer | 撰寫完整文章 |
| link-finder | 外部連結驗證 |
| seo-graph | Neo4j 知識圖譜查詢 |

## 快速開始

```bash
# 設定環境
cd ~/clients/ohya

# 啟動 Neo4j
docker compose up -d

# GSC 授權（首次）
bin/gsc-query --auth

# Scrape 所有文章到 Neo4j
bin/scrape-article --all

# 測試 agent
HERMES_HOME=~/clients/ohya \
  ~/.hermes/hermes-agent/venv/bin/python \
  -m hermes_cli.main --profile seo-graph chat --max-turns 5 --yolo \
  -q "查所有文章"
```

## 目錄結構

```
~/clients/ohya/          專案根目錄
~/workspace/ohya/        agent 產出
```

詳細操作手冊見 [AGENT.md](./AGENT.md)。
