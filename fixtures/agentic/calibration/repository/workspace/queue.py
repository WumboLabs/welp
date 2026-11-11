#!/usr/bin/env python3
"""Offline dispatch queue. Requirements are in README.md and REVIEW.md."""
import argparse
import json
from pathlib import Path
STORE = Path('queue.json')

def load_jobs():
    return json.loads(STORE.read_text())

def ordered(jobs):
    return sorted(jobs, key=lambda j: j['ticket'])

def main(argv=None):
    parser = argparse.ArgumentParser(prog='queue.py')
    sub = parser.add_subparsers(dest='operation', required=True)
    add = sub.add_parser('add'); add.add_argument('label')
    add.add_argument('--priority', choices=['low','normal','high'], default='normal')
    ls = sub.add_parser('list'); ls.add_argument('--json', action='store_true')
    done = sub.add_parser('done'); done.add_argument('ticket', type=int)
    args = parser.parse_args(argv)
    jobs = load_jobs()
    if args.operation == 'add':
        ticket = max((j['ticket'] for j in jobs), default=0)+1
        jobs.append(dict(ticket=ticket,label=args.label,priority=args.priority,done=False))
        STORE.write_text(json.dumps(jobs)+'\n')
        print(ticket)
    elif args.operation == 'done':
        for j in jobs:
            if j['ticket'] == args.ticket:
                j['done'] = True; STORE.write_text(json.dumps(jobs)+'\n'); return
        raise SystemExit('unknown ticket')
    else:
        selected = ordered(jobs)
        if args.json: print(json.dumps(dict(jobs=selected)))
        else:
            for j in selected: print(str(j['ticket'])+': '+j['label'])
if __name__ == '__main__': main()
