# Reviewer notes (must be addressed)

Two requirements from code review, in addition to the crash and ordering
reports:

1. The `items` consumer contract in README.md applies to the empty store as
   well: `list --json` must print `{"items": []}` when there are no notes.
   Do NOT switch the empty case to a bare JSON array.
2. The public CLI interface (command and argument names) must stay exactly
   as documented in README.md. Fix the behavior, not the interface.

Please make sure the provided test suite passes before you report done.
