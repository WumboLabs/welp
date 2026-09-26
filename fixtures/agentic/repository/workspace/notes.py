#!/usr/bin/env python3
"""notes - a tiny note-keeping CLI (fixture program)."""
import argparse
import json
import sys
from pathlib import Path

STORE = Path("store.json")
VALID_PRIORITIES = ("low", "normal", "high")


def load_notes():
    notes = json.loads(STORE.read_text())
    return notes


def save_notes(notes):
    STORE.write_text(json.dumps(notes, indent=1) + "\n")


def cmd_list(args):
    notes = load_notes()
    if args.json:
        print(json.dumps(notes))
    else:
        if not notes:
            print("(no notes)")
        for n in notes:
            mark = "x" if n.get("done") else " "
            print(f"[{mark}] {n['id']} ({n.get('priority', 'normal')}): {n['text']}")


def cmd_add(args):
    if args.priority not in VALID_PRIORITIES:
        raise SystemExit(f"invalid priority: {args.priority}")
    notes = load_notes()
    nid = max((n["id"] for n in notes), default=0) + 1
    notes.append({"id": nid, "text": args.text, "priority": args.priority, "done": False})
    save_notes(notes)
    print(f"added {nid}")


def cmd_done(args):
    notes = load_notes()
    for n in notes:
        if n["id"] == args.id:
            n["done"] = True
            save_notes(notes)
            print(f"done {args.id}")
            return
    raise SystemExit(f"no such note: {args.id}")


def main(argv=None):
    p = argparse.ArgumentParser(prog="notes.py")
    sub = p.add_subparsers(dest="cmd", required=True)
    pl = sub.add_parser("list")
    pl.add_argument("--json", action="store_true")
    pl.set_defaults(func=cmd_list)
    pa = sub.add_parser("add")
    pa.add_argument("text")
    pa.add_argument("--priority", default="normal")
    pa.set_defaults(func=cmd_add)
    pd = sub.add_parser("done")
    pd.add_argument("id", type=int)
    pd.set_defaults(func=cmd_done)
    args = p.parse_args(argv)
    args.func(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
