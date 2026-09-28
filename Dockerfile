# Single container: FastAPI serves the API and the built dashboard.
# The demo-pack rasters must be present in data/demo_pack before building
# (scripts/demo_pack_archive.py fetch).

FROM node:24-slim AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8080
WORKDIR /app
COPY backend/pyproject.toml backend/
COPY backend/src backend/src
RUN pip install --no-cache-dir ./backend
COPY data/demo_pack data/demo_pack
COPY --from=web /web/dist frontend/dist
ENV GEOINTX_PACK_DIR=/app/data/demo_pack \
    GEOINTX_VAR_DIR=/tmp/geointx \
    GEOINTX_FRONTEND_DIST=/app/frontend/dist
EXPOSE 8080
CMD ["python", "-c", "from geointx.api.app import main; main()"]
