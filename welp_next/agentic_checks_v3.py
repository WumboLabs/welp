"""Proposed checker/3: bounded script equivalence and native log-level case.

Historical checker/2 and calibration oracles remain unchanged. This checker
is selectable for SOFTWARE_TEST preparation only, not accepted scored science.
"""
import copy
import json
import shlex
from pathlib import Path

from . import agentic_checks, calibration_checks, policy

VERSION = 3


def identity():
    """Bind the scientific predicates used here, not incidental host helpers."""
    return policy.digest({module.__name__: policy.file_sha(Path(module.__file__))
                          for module in (agentic_checks, calibration_checks)} |
                         {__name__: policy.file_sha(Path(__file__))})


def _script_command(command, prescribed):
    # Deliberately a finite shell grammar, not a claim to understand arbitrary
    # shell programs. No redirects, substitutions, flags, arguments or suffixes.
    if not isinstance(command, str) or any(c in command for c in ('$','`','\n','\r')):
        return False
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        lexer.commenters = ''
        words = list(lexer)
    except ValueError:
        return False
    if len(words) >= 3 and words[0] == 'cd' and words[1] in ('.', '/workspace', '/workspace/') and words[2] == '&&':
        words = words[3:]
    if words and words[0] in ('sh', '/bin/sh', 'bash', '/bin/bash'):
        words = words[1:]
    script = prescribed.removeprefix('./')
    return len(words) == 1 and words[0] in ('./' + script, '/workspace/' + script)


def verification(record, transcript, prescribed):
    actions = [e for e in transcript if e.get('role') == 'assistant'
               and e.get('tool') in ('run', 'write_file')]
    last = actions[-1] if actions else {}
    command = last.get('args', {}).get('command')
    if last.get('tool') != 'run' or not _script_command(command, prescribed):
        return False
    observations = [e.get('observation', {}) for e in transcript
                    if e.get('role') == 'observation' and e.get('turn') == last.get('turn')]
    if len(observations) != 1:
        return False
    obs = observations[0]
    receipt = (obs.get('tool') == 'run' and obs.get('args') == last.get('args')
               and obs.get('ok') is True and type(obs.get('exit_code')) is int
               and obs['exit_code'] == 0 and obs.get('launched') is True
               and obs.get('timed_out') is False and obs.get('snapshot_complete') is True
               and not obs.get('harness_failure') and not obs.get('snapshot_error'))
    commands = [c for c in record.get('commands', []) if c.get('turn') == last.get('turn')]
    return bool(receipt and len(commands) == 1 and commands[0].get('command') == command
                and commands[0].get('ok') is True and commands[0].get('exit_code') == 0)


def checks(record, transcript, fixture):
    inherited = ([] if fixture.spec.get('calibration_id') else
                 agentic_checks.checks(record, transcript, fixture))
    out = [c for c in inherited if c['id'] != 'exact_final_verification']
    command = fixture.spec.get('verification_command')
    if command:
        out.append({'id': 'required_verification_execution',
                    'pass': verification(record, transcript, command),
                    'detail': 'Required protected script in /workspace; successful original sandbox receipt after all writes/commands; bounded direct/shell/cd equivalents only'})
    return out


def acceptance(receipt, record, fixture):
    """Normalize only the catalog whose frozen runtime itself normalizes case."""
    if fixture.name != 'system' or fixture.spec.get('log_level_case') != 'native-upper':
        return receipt
    out = copy.deepcopy(receipt)
    try:
        text = record['final_state']['files']['config/catalog.json']['content']
        level = json.loads(text).get('log_level')
    except (KeyError, TypeError, ValueError):
        level = None
    valid = isinstance(level, str) and level.upper() in ('DEBUG', 'INFO', 'WARNING', 'ERROR')
    for check in out['checks']:
        if check['id'] == 'config_log_level_valid':
            check.update({'pass': valid,
                          'detail': 'catalog.py normalizes with upper(); original level=' + repr(level)})
    if out.get('acceptance_pass') is not None:
        out['acceptance_pass'] = all(c['pass'] for c in out['checks'])
    return out
