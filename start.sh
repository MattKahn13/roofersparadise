#!/bin/sh
# On first boot the mounted volume (/data) is empty. Seed it from the hail data baked into
# the image so the map is live immediately (no slow in-machine re-fetch). Subsequent boots
# keep the volume's data (which the daily refresh + accounts DB have grown).
set -e
if [ ! -d /data/hail ] || [ -z "$(ls -A /data/hail 2>/dev/null)" ]; then
  echo "start.sh: seeding /data from baked image data ..."
  mkdir -p /data
  cp -r /app/data/. /data/
  echo "start.sh: seed complete ($(ls /data/hail 2>/dev/null | wc -l) year dirs)"
fi
exec uvicorn app:app --host 0.0.0.0 --port "${PORT:-8080}"
