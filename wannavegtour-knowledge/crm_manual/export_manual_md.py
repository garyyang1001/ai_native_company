#!/usr/bin/env python3
"""把 crm_assistant_kb.manual_entries(approved)匯出成人類可讀的 Markdown 手冊。

正本永遠是資料庫(可審計:manual_revisions 留痕);這份 .md 是給人看的快照,
每次手冊有改版就重跑一次並 commit,GitHub 上即可追蹤手冊演進。

用法: python3 export_manual_md.py [輸出路徑,預設 CRM小幫手手冊.md]
"""
import subprocess
import sys
from datetime import date

OUT = sys.argv[1] if len(sys.argv) > 1 else "CRM小幫手手冊.md"
SEP = "\x1f"  # 欄位分隔(unit separator),內容不會撞到
RS = "\x1e"   # 紀錄分隔(record separator):answer 是多行文字,不能用換行切列

SQL = f"""
select domain, entry_code, title, coalesce(ui_path,''), version, answer
from manual_entries
where status='approved'
order by domain, entry_code;
"""

raw = subprocess.run(
    ["docker", "exec", "wannaveg-dev-pg", "psql", "-U", "wv", "-d", "crm_assistant_kb",
     "-tA", "-F", SEP, "-R", RS, "-c", SQL],
    capture_output=True, text=True, check=True,
).stdout

rows = [rec.split(SEP) for rec in raw.split(RS) if rec.strip()]

lines = [
    "# CRM 小幫手手冊(內部同仁版)",
    "",
    f"> 匯出日期:{date.today().isoformat()} | 條目數:{len(rows)} | "
    "正本在資料庫 crm_assistant_kb.manual_entries(改版軌跡見 manual_revisions)",
    "> 本檔由 export_manual_md.py 自動產生,**請勿手改**;要改內容走小幫手送審流程。",
    "",
]

cur_domain = None
for domain, code, title, ui_path, version, answer in rows:
    if domain != cur_domain:
        cur_domain = domain
        lines += [f"## {domain}", ""]
    lines.append(f"### {code} {title}(v{version})")
    if ui_path:
        lines.append(f"*頁面:{ui_path}*")
    lines += ["", answer.strip(), ""]

with open(OUT, "w", encoding="utf-8") as f:
    f.write("\n".join(lines) + "\n")

print(f"已匯出 {len(rows)} 條 → {OUT}")
