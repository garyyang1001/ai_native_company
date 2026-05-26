#!/bin/bash
# 用法:bash backup.sh daily|weekly|monthly
set -euo pipefail
TYPE="${1:?usage: backup.sh daily|weekly|monthly}"
BASE="$HOME/.hermes/credentials/wannavegtour/op_kernel"
DIR="$BASE/backup/$TYPE"
mkdir -p "$DIR" && chmod 700 "$DIR"

case "$TYPE" in
  daily)   FNAME="$(date +%Y-%m-%d).sql.gz" ;;
  weekly)  FNAME="$(date +%Y-W%V).sql.gz" ;;
  monthly) FNAME="$(date +%Y-%m).sql.gz" ;;
  *) echo "bad type"; exit 1 ;;
esac

OUT="$DIR/$FNAME"
TMP="$OUT.tmp.$$"

# trap cleanup on any exit (success or failure)
trap 'rm -f "$TMP"' EXIT

# 絕對路徑(cron PATH 不全)+ stderr 進 log
# ★ Wave 2 HIGH#I1:atomic write,先寫 tmp,gzip -t 驗,才 mv
/usr/bin/docker exec op-assistant-kernel pg_dump \
  -U op_kernel -d op_assistant_kernel \
  --no-owner --no-acl \
  2>> "$BASE/backup/backup.log" \
  | gzip > "$TMP"

# 驗 gzip integrity(壞檔會 non-zero exit)
if ! /usr/bin/gzip -t "$TMP" 2>>"$BASE/backup/backup.log"; then
  echo "[$(date -Iseconds)] backup ${TYPE}: gzip integrity check FAILED" >> "$BASE/backup/backup.log"
  exit 1   # trap cleans tmp
fi

# 大小合理性檢查(空檔通常 <100 bytes,要小心)
if [ "$(stat -c%s "$TMP")" -lt 100 ]; then
  echo "[$(date -Iseconds)] backup ${TYPE}: dump <100 bytes,suspicious" >> "$BASE/backup/backup.log"
  exit 1
fi

mv "$TMP" "$OUT"
chmod 600 "$OUT"
trap - EXIT   # 成功了,取消 cleanup trap

# Retention
case "$TYPE" in
  daily)   find "$DIR" -name "*.sql.gz" -mtime +14 -delete ;;
  weekly)  find "$DIR" -name "*.sql.gz" -mtime +90 -delete ;;
  monthly) find "$DIR" -name "*.sql.gz" -mtime +400 -delete ;;
esac

echo "[$(date -Iseconds)] backup ${TYPE}: $FNAME ($(du -h "$OUT" | cut -f1))" >> "$BASE/backup/backup.log"
