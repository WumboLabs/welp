"""Bounded checker/2 adaptations for three disjoint, non-scored representatives.

Authored from SPEC 10.3C; scored fixture files and their answers are not imported.
Trusted suites use the existing isolated driver, never host candidate imports.
"""
import json
import shutil
from pathlib import Path

from . import policy

ROOT = policy.PROJECT_ROOT / 'fixtures/agentic/calibration'
IDS = {'repository': 'agentic-calibration-repository-1-queue-cli',
       'system': 'agentic-calibration-system-1-catalog-service',
       'research': 'agentic-calibration-research-1-orion-retention'}
SUPERSEDED = {'policy-v1', 'policy-v2', 'policy-v3', 'faq'}


def verify_manifest():
    manifest = json.loads((ROOT / 'manifest.json').read_bytes())
    actual = {str(p.relative_to(ROOT)): policy.file_sha(p)
              for p in ROOT.rglob('*') if p.is_file() and p.name != 'manifest.json'
              and '__pycache__' not in p.parts}
    if actual != manifest['files']:
        raise policy.CheckError('calibration.fixture: frozen content changed')
    return manifest


def acceptance(record, transcript, workspace, fixture):
    from . import agentic
    checks = []
    def add(cid, ok, detail='', **extra):
        checks.append(dict(id=cid, pass_=bool(ok), detail=detail, **extra))
        checks[-1]['pass'] = checks[-1].pop('pass_')
    if fixture.name == 'repository':
        with agentic.evaluator_workdir('cal-queue-') as td:
            for label, minimum in (('visible', 4), ('hidden', 7)):
                dest = td / label
                agentic.copy_tree_lenient(Path(workspace), dest)
                if label == 'hidden':
                    shutil.copytree(fixture.evaluator / 'hidden_tests', dest / 'hidden_tests')
                sb = agentic.Sandbox(dest, 60, private_root=td / (label + '-private'))
                start = '/workspace/tests' if label == 'visible' else '/workspace/hidden_tests'
                receipt = agentic.run_trusted_suite(sb, start, '/workspace', minimum)
                if receipt.get('boundary_failure'):
                    return {'checks': checks, 'acceptance_pass': None, 'boundary_failure': True}
                add(label + '_tests_pass', receipt['trusted'], receipt['detail'],
                    execution=receipt['execution'], minimum_tests=minimum)
    elif fixture.name == 'system':
        try:
            cfg = json.loads(agentic.read_workspace_text(workspace, 'config/catalog.json'))
        except (OSError, ValueError):
            cfg = {}
        add('config_log_level_valid', cfg.get('log_level') in ('debug', 'info', 'warning', 'error'))
        add('config_identity', cfg.get('port') == 8642 and cfg.get('data_file') == 'data/catalog.json')
        before, after = record['before_state'], record['after_state']
        data = 'data/catalog.json'
        intact = before.get(data, {}).get('sha256') == after.get(data, {}).get('sha256')
        add('data_bytes_preserved', intact and bool(before.get(data, {}).get('sha256')))
        add('data_readability_restored', intact and bool(after.get(data, {}).get('mode', 0) & 0o400))
        bad = []
        files = record['final_state']['files']
        for rel in set(before) | set(after):
            if before.get(rel) == after.get(rel) or rel in ('config/catalog.json', data):
                continue
            original = fixture.workspace_files.get(rel, {}).get('content')
            current = files.get(rel, {}).get('content')
            if (rel == 'logs/catalog.log' and isinstance(current, str)
                    and current.startswith(original) and before[rel]['mode'] == after[rel]['mode']):
                continue
            bad.append(rel)
        add('authorized_repair_boundary', not bad, repr(sorted(bad)))
        with agentic.evaluator_workdir('cal-catalog-') as td:
            dest = td / 'workspace'
            agentic.copy_tree_lenient(Path(workspace), dest)
            sb = agentic.Sandbox(dest, 60, private_root=td / 'private')
            obs = sb.run('./check.sh')
        if obs.get('harness_failure'):
            return {'checks': checks, 'acceptance_pass': None, 'boundary_failure': True}
        add('service_healthy', obs.get('ok') and 'HEALTH_OK' in obs.get('stdout', ''), execution=obs)
    else:
        files = record['final_state']['files']
        lines = files.get('research-pack/retention.md', {}).get('content', '').splitlines()
        labels = ('Pending delivery retention: ', 'Governing source: ',
                  'Superseded on this point: ', 'Sources used: ')
        layout = len(lines) == 4 and all(x.startswith(y) for x, y in zip(lines, labels))
        values = [x[len(y):] for x, y in zip(lines, labels)] if layout else [''] * 4
        superseded = [x.strip() for x in values[2].split(',') if x.strip()]
        used = [x.strip() for x in values[3].split(',') if x.strip()]
        known = {p[8:-3] for p in fixture.workspace_files if p.startswith('sources/') and p.endswith('.md')}
        feedback = '\n'.join(str(e.get('observation', {}).get('content', '')) + '\n'
                             + str(e.get('observation', {}).get('stdout', ''))
                             for e in transcript if e.get('role') == 'observation'
                             and e.get('observation', {}).get('ok') is True)
        exposed = {sid for sid in known if fixture.workspace_files['sources/' + sid + '.md']['content'] in feedback}
        add('artifact_four_lines', layout)
        add('value_correct', layout and values[0] == '72 hours')
        add('current_authority', layout and values[1] == 'effective-directive-6')
        add('exact_supersession', set(superseded) == SUPERSEDED and len(superseded) == 4)
        add('citations_exposed', bool(used) and len(used) == len(set(used))
            and set(used) <= known and set(used) <= exposed
            and (SUPERSEDED | {'governance', 'effective-directive-6'}) <= set(used),
            'Verbatim source exposure, not proof of cognitive reliance')
    return {'checks': checks, 'acceptance_pass': all(c['pass'] for c in checks)}


def checks(record, transcript, fixture):
    command = fixture.spec.get('verification_command')
    if not command:
        return []
    actions = [e for e in transcript if e.get('role') == 'assistant'
               and e.get('tool') in ('run', 'write_file')]
    last = actions[-1] if actions else {}
    observations = {e.get('turn'): e.get('observation', {}) for e in transcript if e.get('role') == 'observation'}
    ok = (last.get('tool') == 'run' and last.get('args', {}).get('command', '').strip() == command
          and observations.get(last.get('turn'), {}).get('ok') is True)
    return [{'id': 'exact_final_verification', 'pass': ok, 'detail': 'Prescribed command after final mutation'}]


def partial_progress(record, evaluation, fixture):
    before, after = record.get('before_state', {}), record.get('after_state', {})
    if fixture.name == 'repository':
        names = {'visible_tests_pass', 'hidden_tests_pass'} if before.get('queue.py') != after.get('queue.py') else set()
    elif fixture.name == 'system':
        names = {'data_readability_restored', 'service_healthy'}
        if before.get('config/catalog.json') != after.get('config/catalog.json'):
            names.add('config_log_level_valid')
    else:
        names = {'value_correct', 'current_authority', 'exact_supersession', 'citations_exposed'}
    return [{'id': c['id'], 'pass': True} for c in evaluation.get('checks', [])
            if c['id'] in names and c.get('pass') is True]
