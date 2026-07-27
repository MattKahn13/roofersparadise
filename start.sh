#!/bin/sh
# Seed the data dir from the hail data baked into the image so the map is live immediately
# (no slow in-machine re-fetch). Uses $DATA_DIR (default /data). Permission-tolerant: on hosts
# that run the container as non-root, seeding a fresh /data may not be writable -- in that case
# set DATA_DIR=/app/data (the baked location, already present) and the seed is simply skipped.
DATA_DIR="${DATA_DIR:-/data}"
if [ ! -d "$DATA_DIR/hail" ] || [ -z "$(ls -A "$DATA_DIR/hail" 2>/dev/null)" ]; then
  echo "start.sh: seeding $DATA_DIR from baked image data ..."
  mkdir -p "$DATA_DIR" 2>/dev/null || true
  cp -r /app/data/. "$DATA_DIR"/ 2>/dev/null || true
  echo "start.sh: seed done ($(ls "$DATA_DIR/hail" 2>/dev/null | wc -l) year dirs)"
fi
# Tiles read cumulative.parquet. The volume may have been seeded on an earlier deploy (before this
# file existed) and seeding above is skipped when hail/ is present -- so ALWAYS sync it from the image.
[ -f /app/data/cumulative.parquet ] && cp -f /app/data/cumulative.parquet "$DATA_DIR/cumulative.parquet" 2>/dev/null || true
exec uvicorn app:app --host 0.0.0.0 --port "${PORT:-8080}"
