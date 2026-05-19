#!/bin/bash
set -a
source ~/Documents/KPOP\ Agent/kpop-agent/.env
set +a

# 啟動 ngrok
ngrok http 5050 &
sleep 3

# 取得 public URL
NGROK_URL=$(curl -s http://localhost:4040/api/tunnels | python3 -c "import sys,json; print(json.load(sys.stdin)['tunnels'][0]['public_url'])")
echo ""
echo "✅ ngrok URL: $NGROK_URL"
echo "✅ 請到 LINE Developers 把 webhook 改成：$NGROK_URL/webhook"
echo ""

# 啟動 Flask
python3 app.py
