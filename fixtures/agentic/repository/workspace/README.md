# notes CLI

A tiny note-keeping CLI for the demo repository.

## Usage

    python3 notes.py add "some task" [--priority low|normal|high]
    python3 notes.py list [--json]
    python3 notes.py done <id>

Notes are stored in `store.json` (created on first `add`).

## Consumer contract

- `list --json` prints a single JSON object with an `items` key holding the
  (possibly empty) list of notes. Downstream tooling depends on the `items`
  key always being present.
- Listing shows pending notes before done notes; within pending notes,
  higher-priority notes (high > normal > low) appear first; ties break by id.
- The CLI interface (command and argument names) is public and must not change.

## Tests

Run the suite with:

    ./run_tests.sh
