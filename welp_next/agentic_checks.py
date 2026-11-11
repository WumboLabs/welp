"""Prospective checker/2 supplements; pure checks over original evidence.

The frozen checker/1 files remain unchanged. No model code executes here.
"""

VERSION = 2
SUPERSEDED = {'manual-v1', 'manual-v2', 'manual-v3', 'faq'}


def checks(record, transcript, fixture):
    out = []

    def add(name, passed, detail):
        out.append({'id': name, 'pass': bool(passed), 'detail': detail})

    before = record.get('before_state') or {}
    after = record.get('after_state') or {}
    files = (record.get('final_state') or {}).get('files') or {}
    observations = {e.get('turn'): e.get('observation') or {} for e in transcript
                    if e.get('role') == 'observation'}
    command = fixture.spec.get('verification_command')
    if command:
        # A later arbitrary command might mutate state. Conservative ordering
        # avoids pretending a shell regex can prove arbitrary commands read-only.
        actions = [e for e in transcript if e.get('role') == 'assistant'
                   and e.get('tool') in ('run', 'write_file')]
        last = actions[-1] if actions else {}
        add('exact_final_verification', last.get('tool') == 'run'
            and last.get('args', {}).get('command', '').strip() == command
            and observations.get(last.get('turn'), {}).get('ok') is True,
            'exact prescribed command must succeed after all writes/commands')
    if fixture.name == 'system':
        data = 'data/quotes.json'
        intact = bool(before.get(data, {}).get('sha256')) and (
            before.get(data, {}).get('sha256') == after.get(data, {}).get('sha256'))
        add('data_bytes_preserved', intact, 'original data bytes, not merely record shape')
        bad = []
        for path in set(before) | set(after):
            if before.get(path) == after.get(path) or path in ('config/service.json', data):
                continue
            if path == 'logs/service.log':
                original = fixture.workspace_files.get(path, {}).get('content', '')
                current = files.get(path, {}).get('content')
                if (isinstance(current, str) and current.startswith(original)
                        and before.get(path, {}).get('mode') == after.get(path, {}).get('mode')):
                    continue
            bad.append(path)
        add('authorized_repair_boundary', not bad, 'unauthorized changes: ' + repr(sorted(bad)))
        add('data_readability_restored', intact and bool(after.get(data, {}).get('mode', 0) & 0o400),
            'same data, owner-readable after mode-000 fault')
    if fixture.name == 'research':
        text = files.get('research-pack/answer.md', {}).get('content', '')
        lines = text.splitlines()
        labels = ('Maximum recommended consumer batch size: ', 'Governing source: ',
                  'Superseded on this point: ', 'Sources used: ')
        layout = len(lines) == 4 and all(line.startswith(label) for line, label in zip(lines, labels))
        values = [line[len(label):] for line, label in zip(lines, labels)] if layout else [''] * 4

        def ids(value):
            return [part.strip() for part in value.split(',') if part.strip()]

        superseded, used = ids(values[2]), ids(values[3])
        known = {path.removeprefix('sources/').removesuffix('.md')
                 for path in fixture.workspace_files if path.startswith('sources/') and path.endswith('.md')}
        feedback = '\n'.join(str(obs.get('content', '')) + '\n' + str(obs.get('stdout', ''))
                             for obs in observations.values() if obs.get('ok') is True)
        exposed = {sid for sid in known if fixture.workspace_files['sources/' + sid + '.md']['content'] in feedback}
        add('artifact_four_lines', layout, 'exact four named lines, no extra prose')
        add('exact_current_authority', layout and values[0] == '96 messages' and values[1] == 'ops-bulletin-7',
            'effective bulletin, not draft or multiple governing sources')
        add('exhaustive_supersession', layout and set(superseded) == SUPERSEDED
            and len(superseded) == len(SUPERSEDED), 'all three manuals and stale FAQ advice; exclude withdrawn draft')
        add('citations_exposed', layout and bool(used) and len(used) == len(set(used))
            and set(used) <= known and set(used) <= exposed
            and (SUPERSEDED | {'ops-bulletin-7', 'governance'}) <= set(used),
            'exact source IDs with verbatim source content in successful tool feedback; not proof of cognition')
    return out


def partial_progress(record, evaluation, fixture):
    """Only newly demonstrated task milestones, never initial invariants."""
    if fixture.spec.get('checker_version', 1) == 1:
        return [{'id': c['id'], 'pass': bool(c['pass'])} for c in evaluation.get('checks', [])]
    before, after = record.get('before_state') or {}, record.get('after_state') or {}
    if fixture.name == 'research':
        names = {'exact_current_authority', 'exhaustive_supersession', 'citations_exposed'}
    elif fixture.name == 'system':
        names = {'data_readability_restored', 'service_healthy'}
        if before.get('config/service.json') != after.get('config/service.json'):
            names.add('config_log_level_valid')
    else:
        target = 'notes.py' if fixture.name == 'repository' else 'formatters.py'
        names = {c['id'] for c in evaluation.get('checks', [])
                 if c.get('execution') and c.get('minimum_tests')}
        if before.get(target) == after.get(target):
            names.clear()
    return [{'id': c['id'], 'pass': True} for c in evaluation.get('checks', [])
            if c['id'] in names and c.get('pass') is True]
