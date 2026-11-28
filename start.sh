#!/bin/bash
# Container entrypoint: migrate, then run FastAPI (internal :8000) and the
# Next.js server (public :3000). If either process exits, stop the other and
# exit so Docker's restart policy brings the container back.
set -euo pipefail

cd /app/backend
python -m app.cli migrate   # every person's database (moves single-user data the first time)

python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-access-log &
API_PID=$!

# Don't open the web port until the API answers, so early requests don't fail.
for _ in $(seq 1 60); do
  python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=1)" 2>/dev/null && break
  kill -0 "$API_PID" 2>/dev/null || { echo "API failed to start" >&2; exit 1; }
  sleep 0.5
done

cd /app/frontend
HOSTNAME=0.0.0.0 PORT=3000 node server.js &
WEB_PID=$!

trap 'kill -TERM "$API_PID" "$WEB_PID" 2>/dev/null || true' TERM INT

set +e
wait -n "$API_PID" "$WEB_PID"
status=$?
kill -TERM "$API_PID" "$WEB_PID" 2>/dev/null
wait
exit "$status"
