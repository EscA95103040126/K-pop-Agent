#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

set -a
if [ -f "$PROJECT_ROOT/.env" ]; then
  source "$PROJECT_ROOT/.env"
fi
set +a

PORT="${PORT:-5000}"

# 啟動 ngrok
ngrok http "$PORT" &
sleep 3

# 取得 public URL
NGROK_URL=$(curl -s http://localhost:4040/api/tunnels | python3 -c "import sys,json; print(json.load(sys.stdin)['tunnels'][0]['public_url'])")
echo ""
echo "✅ ngrok URL: $NGROK_URL"
echo "✅ 請到 LINE Developers 把 webhook 改成：$NGROK_URL/webhook"
echo ""

# 啟動 Flask
cd "$PROJECT_ROOT"
python3 app.py
