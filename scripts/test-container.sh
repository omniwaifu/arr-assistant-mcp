#!/usr/bin/env bash
# Build and exercise the release container without any real Arr credentials.
set -euo pipefail

image="arr-assistant-mcp:test"
container_id=""
cleanup() {
  if [[ -n "$container_id" ]]; then
    docker logs "$container_id"
    docker rm -f "$container_id" >/dev/null
  fi
}
trap cleanup EXIT

docker build --tag "$image" .
container_id=$(docker run -d --read-only --cap-drop ALL \
  --security-opt no-new-privileges:true -p 127.0.0.1::8000 \
  -e ARR_MCP_TOKEN="test-token-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" \
  -e ARR_MCP_ALLOWED_HOSTS=media.example.com \
  -e RADARR_API_KEY= -e SONARR_API_KEY= "$image")
binding=$(docker port "$container_id" 8000/tcp)
export ARR_ASSISTANT_TEST_HTTP_URL="http://$binding"

uv run python - <<'PY'
import os
import time

import httpx

url = os.environ["ARR_ASSISTANT_TEST_HTTP_URL"]
with httpx.Client(timeout=2) as client:
    for attempt in range(60):
        try:
            if client.get(f"{url}/healthz").status_code == 200:
                break
        except httpx.TransportError:
            pass
        time.sleep(0.5)
    else:
        raise SystemExit("Container did not become ready within 30 seconds")
PY

uv run pytest tests/test_http.py -v \
  -k 'authentication_and_request_guards or concurrent_http_clients'

# Exercise the image's own health check too, as the non-root runtime user.
docker exec "$container_id" python -c \
  "import httpx; httpx.get('http://127.0.0.1:8000/healthz').raise_for_status()"
