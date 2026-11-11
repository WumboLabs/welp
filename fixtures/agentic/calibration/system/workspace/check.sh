#!/bin/sh
ip link set lo up 2>/dev/null || true
python3 catalog.py >> logs/catalog.log 2>&1 &
SVC=$!
i=0
while [ "$i" -lt 20 ]; do
  if python3 -c "import json,urllib.request;d=json.load(urllib.request.urlopen('http://127.0.0.1:8642/health',timeout=1));assert d==dict(status='ok',records=3)" 2>/dev/null; then
    kill "$SVC" 2>/dev/null; wait "$SVC" 2>/dev/null
    echo HEALTH_OK; exit 0
  fi
  i=$((i+1)); sleep 0.5
done
kill "$SVC" 2>/dev/null; wait "$SVC" 2>/dev/null
echo HEALTH_FAIL; exit 1
