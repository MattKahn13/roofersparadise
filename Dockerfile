# RoofersParadise -- one container: map + landing + auth + alerts.
# Full python image (NOT -slim): rasterio/pyogrio bundle GDAL in their wheels, but GDAL still
# dynamically links system libs (libexpat.so.1, etc.) that -slim omits -> ImportError at import.
# The full image ships those libs (and curl for the healthcheck), avoiding a whack-a-mole of .so files.
FROM python:3.13
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# DATA_DIR points at the mounted volume; ENABLE_WORKERS turns on the poller + daily refresh.
ENV DATA_DIR=/data ENABLE_WORKERS=1 PORT=8080
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD curl -fsS "http://localhost:${PORT}/healthz" || exit 1

# start.sh seeds the empty volume from the baked-in hail data on first boot, then serves.
CMD ["sh", "/app/start.sh"]
