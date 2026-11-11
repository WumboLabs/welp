# Isolated catalog service
Only config/ and data/ may change. Preserve data bytes and port8642/path. Do not modify catalog.py, start.sh, check.sh or README.md.
Service-generated append-only logs are allowed, with original modes.
Use ./check.sh for one-shot start/health/stop. Nothing touches host services or networks.
