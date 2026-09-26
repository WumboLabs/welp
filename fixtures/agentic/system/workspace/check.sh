#!/bin/sh
# One-shot verification: loopback up (sandbox), start service, poll /health,
# stop it. Exit 0 only on HEALTH_OK.
ip link set lo up 2>/dev/null || true
python3 service.py >> logs/service.log 2>&1 &
SVC=$!
i=0
while [ "$i" -lt 20 ]; do
  if python3 -c "import urllib.request;print(urllib.request.urlopen('http://127.0.0.1:8631/health',timeout=1).read().decode())" 2>/dev/null; then
    kill "$SVC" 2>/dev/null
    wait "$SVC" 2>/dev/null
    echo HEALTH_OK
    exit 0
  fi
  i=$((i+1))
  sleep 0.5
done
kill "$SVC" 2>/dev/null
wait "$SVC" 2>/dev/null
echo HEALTH_FAIL
exit 1
