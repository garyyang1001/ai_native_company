#!/usr/bin/env python3
"""把手冊生成工作流的輸出載入 crm_assistant_kb.manual_entries(draft)。

用法: python3 load_entries.py <workflow_output.json> [--unverified 領域1,領域2]
冪等: 以 entry_code upsert(draft 重載會覆蓋;approved 不動)。
"""
import json, subprocess, sys

UNVERIFIED = set()
args = sys.argv[1:]
if "--unverified" in args:
    i = args.index("--unverified")
    UNVERIFIED = set(args[i+1].split(","))
    args = args[:i]
src = json.load(open(args[0]))
payload = src["result"]["payload"] if "result" in src else src["payload"]

def q(s):  # dollar-quote,標籤避開內文
    tag = "qq1"
    while f"${tag}$" in (s or ""):
        tag += "x"
    return f"${tag}${s or ''}${tag}$"

def arr(xs):
    return "ARRAY[" + ",".join(q(x) for x in xs) + "]::text[]" if xs else "'{}'::text[]"

stmts = []
for dom in payload:
    by = "agent_unverified" if dom["domain"] in UNVERIFIED else "agent"
    for e in dom["entries"]:
        stmts.append(
            "INSERT INTO manual_entries (entry_code, domain, title, question_forms, answer, ui_path, source_refs, status, updated_by) VALUES ("
            f"{q(e['entry_code'])}, {q(dom['domain'])}, {q(e['title'])}, {arr(e.get('question_forms', []))}, "
            f"{q(e['answer'])}, {q(e.get('ui_path',''))}, {arr(e.get('source_refs', []))}, 'draft', {q(by)}) "
            "ON CONFLICT (entry_code) DO UPDATE SET title=EXCLUDED.title, question_forms=EXCLUDED.question_forms, "
            "answer=EXCLUDED.answer, ui_path=EXCLUDED.ui_path, source_refs=EXCLUDED.source_refs, "
            "updated_by=EXCLUDED.updated_by, updated_at=now() WHERE manual_entries.status='draft';")

sql = "\n".join(stmts) + "\nSELECT updated_by||': '||count(*) FROM manual_entries GROUP BY updated_by;"
r = subprocess.run(["docker", "exec", "-i", "wannaveg-dev-pg", "psql", "-U", "wv", "-d", "crm_assistant_kb", "-tA", "-v", "ON_ERROR_STOP=1"],
                   input=sql.encode(), capture_output=True)
print(r.stdout.decode()[-300:])
if r.returncode != 0:
    print("ERR:", r.stderr.decode()[-500:]); sys.exit(1)
