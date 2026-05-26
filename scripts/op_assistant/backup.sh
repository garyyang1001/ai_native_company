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
# 絕對路徑(cron PATH 不全)+ stderr 進 log
/usr/bin/docker exec op-assistant-kernel pg_dump \
  -U op_kernel -d op_assistant_kernel \
  --no-owner --no-acl \
  2>> "$BASE/backup/backup.log" \
  | gzip > "$OUT"

chmod 600 "$OUT"

# Retention
case "$TYPE" in
  daily)   find "$DIR" -name "*.sql.gz" -mtime +14 -delete ;;
  weekly)  find "$DIR" -name "*.sql.gz" -mtime +90 -delete ;;
  monthly) find "$DIR" -name "*.sql.gz" -mtime +400 -delete ;;
esac

echo "[$(date -Iseconds)] backup ${TYPE}: $FNAME ($(du -h "$OUT" | cut -f1))" >> "$BASE/backup/backup.log"
