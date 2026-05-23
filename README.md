# AI Native Company

中文名稱：AI 原生公司

AI Native Company is a working repository for turning an AI-native company
operating model into a small, durable, and verifiable local system.

The goal is not to build a generic SEO agent, a large company brain, or a
collection of disconnected automations. The goal is to define a company kernel
where real agents can do work, leave structured records, and make their inputs,
outputs, sources, artifacts, failures, reviews, approvals, and cleanup state
available for later inspection.

## Core Direction

This repository starts from a simple principle:

> Raw data is not company memory.

An AI-native company needs every meaningful data input and output to be
readable, recordable, reviewable, memory-candidate eligible, and cleanable.
That does not mean every raw log, draft, export, or transcript becomes memory.
It means agent work must leave records that can be verified, deduplicated,
scoped, approved, retained, or removed.

The current kernel is organized around four concerns:

- **Company data contracts**: common record shapes for tasks, source references,
  artifacts, output envelopes, failures, verification reports, memory
  candidates, and profile update candidates.
- **Agent profile registry**: a machine-readable registry of permanent and
  dynamic profiles, including what they can read, write, remember, and clean up.
- **Closed loop kernel prototype**: a local Python prototype for append-only
  lifecycle events, failures, candidates, sandbox replay, approval, and apply
  flows.
- **Public repository guardrails**: secret scanning, branch protection, and
  local output-envelope checks that reduce the chance of publishing credentials
  or operational details.

## Current Status

The repository currently includes:

- A Python closed-loop kernel prototype under `closed_loop_kernel/`
- Unit tests for the kernel, HTTP views, sandbox, PostgreSQL store/schema,
  and agent profile registry
- A company data contract v0
- An agent profile registry v0
- A redacted public reference note for the previous OHYA SEO architecture
- Gitleaks configuration and a GitHub Actions security scan workflow

This is still a local prototype and contract layer, but the kernel runtime uses
PostgreSQL as its source-of-truth database. It is not yet a production agent
runtime or production publishing system.

## Repository Map

- `closed_loop_kernel/` - Python prototype for lifecycle events, approvals,
  sandbox replay, profile registry validation, and local HTTP views
- `data/agent-profile-registry-v0.json` - machine-readable profile registry seed
- `docs/company-data-contract-v0.md` - source contract for company data records
- `docs/agent-profile-registry-v0.md` - profile registry contract and governance
- `docs/antigravity-supervision-workflow.md` - Codex/Antigravity supervision
  workflow
- `spec/` - closed-loop kernel specifications and acceptance criteria
- `tests/` - unit tests for the current prototype and contracts
- `references/ohya-seo-architecture/SNAPSHOT.md` - redacted public-safe
  architecture pattern note
- `.gitleaks.toml` - local and CI secret scanning configuration
- `.github/workflows/security-scan.yml` - GitHub Actions Gitleaks workflow

## Local Verification

Install Python dependencies in a virtual environment:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
```

Set a PostgreSQL connection URL for the kernel runtime:

```bash
export KERNEL_DATABASE_URL='postgresql://USER@HOST:PORT/DBNAME'
```

Run the full PostgreSQL-backed test suite:

```bash
python -m unittest discover -s tests
```

Run the local demo:

```bash
export KERNEL_ALLOW_DESTRUCTIVE_RESET=1  # required; demo resets the target database
python -m closed_loop_kernel.demo
```

Run the local HTTP prototype:

```bash
export KERNEL_ALLOW_DESTRUCTIVE_RESET=1  # required; demo resets the target database
python -m closed_loop_kernel.http_app
```

Only use a throwaway PostgreSQL database for the demo and HTTP prototype. The demo seed path resets the target database before loading sample kernel records.

Then open:

```text
http://127.0.0.1:8765/events
```

## Security Guardrails

This repository is intended to be public-safe. Current guardrails include:

- Gitleaks configuration in `.gitleaks.toml`
- GitHub Actions secret scanning on push and pull request
- GitHub native secret scanning and push protection
- Protected `main` branch with pull-request review required
- Local credential-leak detection inside `validate_output_envelope`

The local output-envelope guardrail scans agent payloads and machine records for
common credential patterns before accepting an output envelope. It intentionally
ignores known metadata fields such as content hashes and timestamps.

## Boundaries

- Do not commit credentials, auth files, runtime logs, production databases, or
  local runtime state.
- Do not treat raw exports, transcripts, logs, or generated artifacts as company
  memory.
- Do not let one profile execute, review, approve, and apply its own work.
- Do not restore private executable reference snapshots into this public
  repository.
- Do not copy client-specific paths, tokens, platform details, or deployment
  assumptions into public architecture documents.

## Design Principle

The durable unit of work is not a chat response. It is a reviewable record:

```text
task -> source evidence -> agent output envelope -> artifact -> verification
     -> review -> approval -> memory candidate -> cleanup or retention
```

That loop is the company kernel. Agents can change, tools can change, and
department applications can be added later, but the record contract should stay
small, explicit, and auditable.

---

## 繁體中文說明 (Traditional Chinese Translation)

### 核心目標

AI 原生公司（AI Native Company）是一個工作用儲存庫，旨在將 AI 原生公司的營運模式轉化為一個輕量、持久且可驗證的本地系統。

我們的目標不是建立一個通用的 SEO 代理人（agent）、一個龐大的公司大腦，或是拼湊一堆零散的自動化工具。我們的目標是定義一個「公司核心內核（company kernel）」，讓真實的代理人能夠在此進行工作、留下結構化記錄，並使其輸入、輸出、來源證據、產物、失敗軌跡、審查意見、批准和清理狀態可供後續審計與檢查。

---

### 核心方向

本儲存庫始於一個簡單的原則：

> 原始數據（Raw data）不等於公司記憶。

一家 AI 原生公司需要將每一筆具備業務意義的資料輸入與輸出，做到「可讀（readable）」、「可記錄（recordable）」、「可審核（reviewable）」、「具備記憶候選資格（memory-candidate eligible）」與「後續可安全清理（cleanable）」。這並不代表要把每一份原始日誌、草稿、匯出檔或逐字稿都變成記憶。它的意思是代理人的工作必須留下可被驗證、去重、劃分範圍、批准、保留或刪除的結構化記錄。

目前的內核主要圍繞四個核心範疇進行組織：

- **公司資料合約（Company data contracts）**：定義任務（tasks）、來源證據（source references）、產物（artifacts）、輸出封包（output envelopes）、失敗記錄（failures）、驗證報告（verification reports）、記憶候選者（memory candidates）及代理人設定更新候選者（profile update candidates）的通用記錄格式。
- **代理人角色註冊表（Agent profile registry）**：一個機器可讀的常駐與動態角色註冊表，規定每個角色可讀、可寫、可記憶和可清理的邊界。
- **閉環內核原型（Closed loop kernel prototype）**：一個用於唯增生命週期事件、失敗捕捉、改進候選、沙盒重播、人工審批及原子套用流程的本地 Python 原型。
- **公共儲存庫安全防線（Public repository guardrails）**：包含機密金鑰掃描、分支保護以及本地輸出封包檢查，杜絕將憑證或營運細節意外發布至公共空間。

---

### 目前狀態

本儲存庫目前包含：

- 位於 `closed_loop_kernel/` 下的 Python 閉環內核原型。
- 針對內核、HTTP 視圖、沙盒、PostgreSQL store/schema 及代理人註冊表的單元測試。
- 公司第一層資料合約 v0 (`docs/company-data-contract-v0.md`)。
- 代理人角色註冊表合約 v0 (`docs/agent-profile-registry-v0.md`)。
- 已進行去敏化（安全屏蔽）的 OHYA SEO 舊架構公共參考說明。
- Gitleaks 配置及 GitHub Actions 安全掃描工作流。

本系統目前仍處於本地原型與合約宣告層，但內核 runtime 已以 PostgreSQL 作為 source of truth；它尚不是生產環境的代理人運行時（agent runtime）或生產發布系統。

---

### 儲存庫地圖

- `closed_loop_kernel/` - 用於生命週期事件、人工審批、沙盒重播、註冊表驗證及本地 HTTP 視圖的 Python 原型。
- `data/agent-profile-registry-v0.json` - 機器可讀的代理人註冊表種子資料庫。
- `docs/company-data-contract-v0.md` - 公司資料記錄的源頭合約。
- `docs/agent-profile-registry-v0.md` - 代理人註冊表合約與安全治理規範。
- `docs/antigravity-supervision-workflow.md` - Codex 與 Antigravity 協同監督工作流。
- `spec/` - 閉環內核的詳細技術規格與原型驗收指標。
- `tests/` - 用於當前原型與資料合約的單元測試。
- `references/ohya-seo-architecture/SNAPSHOT.md` - 去敏化（安全屏蔽）的公共安全架構模式參考筆記。
- `.gitleaks.toml` - 本地與 CI 金鑰憑證掃描配置檔案。
- `.github/workflows/security-scan.yml` - GitHub Actions 的 Gitleaks 安全掃描工作流。

---

### 本地驗證

執行單元測試套件：

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
export KERNEL_DATABASE_URL='postgresql://USER@HOST:PORT/DBNAME'
python -m unittest discover -s tests
```

執行本地 Demo：

```bash
export KERNEL_ALLOW_DESTRUCTIVE_RESET=1  # 必填；demo 會重置目標資料庫
python -m closed_loop_kernel.demo
```

執行本地 HTTP 原型服務：

```bash
export KERNEL_ALLOW_DESTRUCTIVE_RESET=1  # 必填；demo 會重置目標資料庫
python -m closed_loop_kernel.http_app
```

Demo 與 HTTP 原型只能指向一次性 PostgreSQL 測試資料庫；啟動前會重置目標資料庫並載入樣本 kernel records。

接著在瀏覽器打開：

```text
http://127.0.0.1:8765/events
```

---

### 安全防線 (Security Guardrails)

本儲存庫旨在對公共空間安全無害。目前的安全防線包含：

- `.gitleaks.toml` 中的 Gitleaks 配置。
- 在 push 和 pull request 時執行的 GitHub Actions 金鑰憑證掃描。
- GitHub 原生的機密金鑰掃描與推送保護。
- 受保護的 `main` 分支（強制要求 pull-request 合併前必須通過審查）。
- 本地在 `validate_output_envelope` 中執行的憑證洩漏阻斷機制。

本地輸出封包安全防線會在系統接收封包前，靜態掃描代理人的 payload 和機器記錄是否包含常見的憑證特徵（如 API Keys）。此掃描會主動忽略已知的中繼資料欄位（如 content hashes 和時間戳記）。

---

### 邊界與限制

- **嚴禁提交**任何明文憑證、授權檔案、運行期日誌、生產資料庫或本地運行狀態。
- **嚴禁將**未經整理的原始導出資料、逐字稿、日誌或生成的產物直接視為公司記憶。
- **嚴禁讓**單一代理人角色同時負責執行、審查、批准並套用其自身的工作（防範共謀風險）。
- **嚴禁將**私有的可執行架構快照還原至此公共儲存庫中。
- **嚴禁將**特定客戶的實體路徑、Tokens、平台細節或部署假設複製到公共架構文件中。

---

### 設計原則

持久的工作單位不是聊天室的對話回覆，而是**可供審計的結構化記錄**：

```text
任務 (task) ➔ 來源證據 (source evidence) ➔ 輸出封包 (output envelope) ➔ 產物 (artifact) ➔ 沙盒驗證 (verification)
     ➔ 專家審查 (review) ➔ 人工批准 (approval) ➔ 記憶候選者 (memory candidate) ➔ 清理或保留 (cleanup/retention)
```

這個閉環是公司的核心內核。代理人可以更換、工具可以升級、部門應用層也可以在未來陸續新增，但核心的記錄合約必須保持小巧、顯式且可被嚴格審計。
