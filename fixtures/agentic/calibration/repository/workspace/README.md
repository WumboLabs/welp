# Dispatch queue
Commands: python3 queue.py add LABEL [--priority low|normal|high]; list [--json]; done TICKET.
queue.json is a list. Missing or whitespace-only storage means an empty queue, never create it during listing.
JSON listing is exactly {"jobs": [...]} even when empty. Text listing has one ticket: label per line; empty means no lines.
Order: unfinished before done; high, normal, low; within identical status/priority preserve input FIFO order, NOT ticket order.
Run ./run_tests.sh. No downloads or host access.
