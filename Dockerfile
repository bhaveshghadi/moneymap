# syntax=docker/dockerfile:1

# ---------- 1. frontend build (Next.js standalone) ----------
FROM node:22-alpine AS frontend
WORKDIR /fe
ENV NEXT_TELEMETRY_DISABLED=1
# package files first so `npm ci` is cached until dependencies change
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
# baked into the /api rewrite: FastAPI runs in the same container
ENV BACKEND_URL=http://127.0.0.1:8000
RUN npm run build

# ---------- 2. runtime: Python + bare Node runtime (Alpine: both musl) ----------
FROM python:3.13-alpine AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    NEXT_TELEMETRY_DISABLED=1 \
    NODE_ENV=production \
    MONEYMAP_DATA_DIR=/data \
    PYTHONPATH=/app/backend
# libstdc++/libgcc: needed by node · tzdata: TZ=Asia/Kolkata · bash: start.sh
RUN apk add --no-cache libstdc++ libgcc tzdata bash
# just the node binary — no npm, no node_modules beyond what standalone needs
COPY --from=frontend /usr/local/bin/node /usr/local/bin/node

WORKDIR /app/backend
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/alembic.ini ./
COPY backend/alembic ./alembic
COPY backend/app ./app

WORKDIR /app/frontend
COPY --from=frontend /fe/.next/standalone ./
COPY --from=frontend /fe/.next/static ./.next/static
COPY --from=frontend /fe/public ./public

COPY start.sh /app/start.sh
RUN sed -i 's/\r$//' /app/start.sh && chmod +x /app/start.sh && mkdir -p /data

VOLUME ["/data"]
EXPOSE 3000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,sys; urllib.request.urlopen('http://127.0.0.1:3000/api/health', timeout=4); sys.exit(0)" || exit 1
CMD ["/app/start.sh"]
