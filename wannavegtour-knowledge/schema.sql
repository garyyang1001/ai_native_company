-- ============================================================
-- wannavegtour_knowledge — 客服對話知識庫 canonical store
-- PostgreSQL 18 @ wannaveg-dev-pg:5436
-- ============================================================
-- 設計:三層 medallion(bronze/silver/gold),對應「可維護/可整理/可清洗」
--   bronze = 原始匯入,immutable,受限,重洗的真相來源
--   silver = 清洗 + 全面去識別,帶 pipeline 版本,可從 bronze 重建
--   gold   = 問答知識單元 = 對外共用可讀的 canonical(其他 agent 讀這層)
-- 所有 PII 只存在 bronze(本機受限);silver/gold 一律去識別,可安全共用/匯出。
-- ============================================================

-- ---------- bronze:原始層 -------------------------------------------------
-- 每個 LINE 匯出 CSV = 一段對話 = 一個 source_file
CREATE TABLE IF NOT EXISTS source_files (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    filename        text NOT NULL,
    file_sha256     text NOT NULL UNIQUE,          -- 冪等匯入:同檔不重收
    account_name    text,                          -- 帳號名稱(阿玩旅遊…)
    timezone        text,
    download_time   text,
    conv_external_key text,                        -- 從檔名解析的對話鍵(客名/團/日期)
    msg_count       int DEFAULT 0,
    imported_at     timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS raw_turns (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source_file_id  bigint NOT NULL REFERENCES source_files(id) ON DELETE CASCADE,
    seq             int NOT NULL,                  -- 檔內序號
    role            text NOT NULL,                 -- 原始:User / Account
    sender_name     text,                          -- 傳送者名稱(去識別用的已知人名來源)
    sent_date       text,
    sent_time       text,
    sent_ts         timestamptz,                   -- 正規化時間(可能為 NULL)
    raw_text        text NOT NULL,                 -- ⚠ 含 PII,僅本機受限,絕不匯出
    content_sha256  text NOT NULL,
    imported_at     timestamptz NOT NULL DEFAULT now(),
    UNIQUE (source_file_id, seq)
);
CREATE INDEX IF NOT EXISTS raw_turns_file_idx ON raw_turns(source_file_id);

-- ---------- silver:清洗 + 去識別層 ----------------------------------------
CREATE TABLE IF NOT EXISTS clean_turns (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    raw_turn_id     bigint NOT NULL REFERENCES raw_turns(id) ON DELETE CASCADE,
    pipeline_version text NOT NULL,                -- 哪一版清洗規則產的 → 可重洗
    role            text NOT NULL,                 -- 正規化:customer / agent
    clean_text      text,                          -- 清洗 + 去識別後文字(可安全共用)
    is_noise        boolean NOT NULL DEFAULT false,-- 系統佔位/寒暄/廢話
    redaction_count int NOT NULL DEFAULT 0,        -- 去識別了幾處(稽核用)
    cleaned_at      timestamptz NOT NULL DEFAULT now(),
    UNIQUE (raw_turn_id, pipeline_version)         -- 同一 turn 同版只一份
);
CREATE INDEX IF NOT EXISTS clean_turns_ver_idx ON clean_turns(pipeline_version);

-- ---------- gold:canonical 知識單元(對外共用可讀)------------------------
CREATE TABLE IF NOT EXISTS knowledge_units (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source_file_id  bigint REFERENCES source_files(id) ON DELETE SET NULL,
    question        text NOT NULL,                 -- 客人問(已去識別)
    answer          text,                          -- 客服答(已去識別)
    intent          text NOT NULL,                 -- 意圖標籤(對齊 taxonomy)
    confidence      real NOT NULL DEFAULT 0,
    tour_destination text,                         -- 從對話/檔名抽的行程資訊
    tour_date       text,
    tour_code       text,
    lang            text DEFAULT 'zh-Hant',
    quality         real NOT NULL DEFAULT 0,       -- 0-1 品質分,匯出時可過濾
    source_turn_ids bigint[],                      -- 來源 clean_turns
    pipeline_version text NOT NULL,
    label_model     text,                          -- 標記用的模型(gpt-oss:120b…)
    status          text NOT NULL DEFAULT 'active',-- active / stale / rejected
    content_hash    text NOT NULL,                 -- 去重 + 變更偵測
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    UNIQUE (content_hash)
);
CREATE INDEX IF NOT EXISTS ku_intent_idx ON knowledge_units(intent, status);
CREATE INDEX IF NOT EXISTS ku_tour_idx   ON knowledge_units(tour_destination);

-- ---------- 維護 / 稽核:每次 pipeline 跑都留帳 ---------------------------
CREATE TABLE IF NOT EXISTS pipeline_runs (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    stage           text NOT NULL,                 -- ingest / clean / label / export
    pipeline_version text NOT NULL,
    started_at      timestamptz NOT NULL DEFAULT now(),
    finished_at     timestamptz,
    input_count     int DEFAULT 0,
    output_count    int DEFAULT 0,
    status          text NOT NULL DEFAULT 'running',-- running / done / failed
    notes           text
);

-- ---------- 給其他 agent 的唯讀角色(只看得到 gold)----------------------
-- 未來 op-assistant / marketing-agent / 官網 agent 後端用這個帳號連、只能讀 gold。
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'wv_knowledge_reader') THEN
        CREATE ROLE wv_knowledge_reader NOLOGIN;
    END IF;
END $$;
GRANT USAGE ON SCHEMA public TO wv_knowledge_reader;
GRANT SELECT ON knowledge_units TO wv_knowledge_reader;   -- 只開 gold,bronze PII 不給
-- 刻意不用 ALTER DEFAULT PRIVILEGES:避免未來新表(尤其 bronze PII)被自動授權。
-- 每次新增要共用的表,手動 GRANT SELECT ... TO wv_knowledge_reader。
