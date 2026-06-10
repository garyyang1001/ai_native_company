-- CRM 小幫手知識庫(crm_assistant_kb)— Gary 2026-06-10 核准欄位
-- 原則:可監測/觀察/審核/修復;只有 status=approved 會被檢索;修訂史只增不改。
CREATE DATABASE crm_assistant_kb;
\c crm_assistant_kb

CREATE TABLE manual_entries (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    entry_code    text UNIQUE NOT NULL,          -- MAN-訂單-001
    domain        text NOT NULL,                  -- 12 領域之一
    title         text NOT NULL,
    question_forms text[] NOT NULL DEFAULT '{}',  -- 同仁的多種問法(檢索用)
    answer        text NOT NULL,                  -- 標準答案(步驟,繁中)
    ui_path       text,                           -- 頁面路徑+按鈕
    source_refs   text[] NOT NULL DEFAULT '{}',   -- 程式碼出處 file:line
    status        text NOT NULL DEFAULT 'draft'
                  CHECK (status IN ('draft','approved','deprecated')),
    version       integer NOT NULL DEFAULT 1,
    updated_by    text NOT NULL DEFAULT 'agent',  -- agent | gary
    review_log_id uuid,                           -- 源自哪筆送審對話(可追溯)
    created_at    timestamptz NOT NULL DEFAULT now(),
    updated_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_manual_domain_status ON manual_entries (domain, status);

-- 修訂史:只增不改(audit truth)
CREATE TABLE manual_revisions (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    entry_id    uuid NOT NULL REFERENCES manual_entries(id),
    old_answer  text,
    new_answer  text NOT NULL,
    reason      text NOT NULL,
    approved_by text NOT NULL,                    -- gary
    created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE OR REPLACE FUNCTION prevent_revision_mutation() RETURNS trigger AS $$
BEGIN RAISE EXCEPTION 'manual_revisions 只增不改'; END $$ LANGUAGE plpgsql;
CREATE TRIGGER no_update BEFORE UPDATE OR DELETE ON manual_revisions
    FOR EACH ROW EXECUTE FUNCTION prevent_revision_mutation();
