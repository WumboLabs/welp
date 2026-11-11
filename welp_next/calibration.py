"""One fixed, non-scored 16-slot calibration package on the existing Agentic core.

No server lifecycle, scored progression, retries, or adaptive task selection.
Authentic execution remains operator-gated: preparation authorization is not run
permission. SOFTWARE_TEST uses the identical loop with explicitly synthetic I/O.
"""
import json
import signal
import time
from pathlib import Path

from . import agentic, context, diagnostic, policy, preflight, reporting, runner, store

SECTION = 'calibration'
VERSION = 'm3-experimental/1'
IMPLEMENTATION_VERSION = 'm3-lean-admission/1'
# New execution requires separate, campaign-bound human authorization:
# a verified `campaign-activation.json` record in the campaign directory
# (policy.campaign_activation) — never module source mutation.
FROZEN_FIXTURES = {
    'qualification': 'd60a1cb4f819432b06ff1688e6dd303dec4512c1f040367a86dbbdcf6d117310',
    'repository': 'e672f74bef64b8d3e7a205a012ac15b0859306f2137d730a6ac31e43680a85c1',
    'system': '053a5d51dfc1343c8c0ed960de8f920ce489622a3f0ca8e5d06e1743f7c49aff',
    'research': '0791b931f57f2da143d4e9fcba7996d595bb509a68b606be36b4a5c11d2e31db',
}
VECTORS = {
    'qualification': ((10,4096,2048,180,10), (18,8192,3072,360,15)),
    'repository': ((18,12288,3072,420,20), (28,24576,4096,840,30)),
    'system': ((14,8192,2048,300,35), (22,16384,3072,600,45)),
    'research': ((18,12288,3072,420,10), (26,24576,4096,840,15)),
}
INPUT_CAP = 12288
TOTAL_TOKENS = 221184
TOTAL_TURNS = 308
TASK_SECONDS = 7920
OVERHEAD_SECONDS = 9600
ALL_SECONDS = 17520
CHECKER_SECONDS = {'qualification':60, 'repository':180, 'system':120, 'research':30}


def section_path(campaign):
    return Path(campaign) / 'sections' / SECTION


def configuration_identity(profile):
    return policy.digest(policy.scientific_configuration(profile))


def inventory(config):
    if not isinstance(config, dict) or set(config) != {'budget_version','evidence_kind','profiles','adapter'}:
        raise policy.CheckError('calibration.config: exact budget version, evidence kind, profiles and adapter required')
    kind = config['evidence_kind']
    if config['budget_version'] != VERSION or kind not in ('SOFTWARE_TEST','CALIBRATION'):
        raise policy.CheckError('calibration.config: approved experimental limits missing or wrong evidence class')
    if config['adapter'] != 'native_tools' or set(config['profiles']) != {'A','B'}:
        raise policy.CheckError('calibration.config: fixed native A/B pair required')
    profiles = config['profiles']
    for arm, name in (('ON','A'),('OFF','B')):
        profile = profiles[name]
        policy.validate_profile(profile)
        if not policy.is_calibration(profile) or profile['evidence_kind'] != kind:
            raise policy.CheckError('calibration.profile: disjoint methodology/kind required')
        if profile['reasoning']['arm'] != arm or profile['runtime']['context_capacity'] != 16384:
            raise policy.CheckError('calibration.profile: fixed arm and16K capacity required')
        if profile['budgets']['max_tokens'] < 4096 or profile['budgets']['timeout_seconds'] < 180:
            raise policy.CheckError('calibration.profile: approved per-response geometry unavailable')
        if kind == 'CALIBRATION' and (profile['model']['model_key'] != 'qwen35-9b'
                or profile['model']['artifact']['sha256'] != '03b74727a860a56338e042c4420bb3f04b2fec5734175f4cb9fa853daf52b7e8'):
            raise policy.CheckError('calibration.profile: exact approved9B artifact required')
        if kind == 'CALIBRATION' and (
                profile['model']['tokenizer_chat_template']['sha256'] !=
                '7f0e529032c25183bcd66c7f238da2d377f43be754a94e2725a58c4e16d2ed67'
                or policy.sampling_settings(profile) !=
                {'min_p':0.05,'seed':20261023,'temperature':0.0,'top_k':40,'top_p':0.95}
                or profile['runtime']['engine']['name'] != 'llama.cpp'):
            raise policy.CheckError('calibration.profile: incompatible approved scientific settings')
    for field in ('artifact','tokenizer_chat_template'):
        if profiles['A']['model'][field]['sha256'] != profiles['B']['model'][field]['sha256']:
            raise policy.CheckError('calibration.contrast: model/tokenizer substitution')
    if policy.sampling_settings(profiles['A']) != policy.sampling_settings(profiles['B']):
        raise policy.CheckError('calibration.contrast: unequal sampler')
    if profiles['A']['context'] != profiles['B']['context']:
        raise policy.CheckError('calibration.contrast: unequal context')
    for field in ('backend', 'context_capacity'):
        if profiles['A']['runtime'][field] != profiles['B']['runtime'][field]:
            raise policy.CheckError('calibration.contrast: unequal runtime '+field)
    if profiles['A']['runtime']['engine']['name'] != profiles['B']['runtime']['engine']['name']:
        raise policy.CheckError('calibration.contrast: unequal inference interface')
    controls = [profiles[name]['reasoning']['controls'] for name in ('A', 'B')]
    if controls != [{'chat_template_kwargs': {'enable_thinking': True}},
                    {'chat_template_kwargs': {'enable_thinking': False}}]:
        raise policy.CheckError('calibration.contrast: exact native reasoning controls required')
    cells, fixtures = [], {}
    for name, rungs in VECTORS.items():
        fixtures[name] = agentic.load_fixture(name, calibration=True)
        if policy.digest(fixtures[name]) != FROZEN_FIXTURES[name]:
            raise policy.CheckError('calibration.fixture: not the frozen representative definition')
        for rung, vector in zip(('L','H'), rungs):
            for configuration in ('A','B'):
                number = len(cells) + 1
                limits = dict(zip(agentic.LIMIT_KEYS, vector))
                limits.update(evidence_kind=kind, source='SPEC10.3C operator-approved provisional '+VERSION)
                agentic.validate_limits(limits)
                cells.append({'id':f'{number:02d}-{name}-{rung.lower()}-{configuration.lower()}',
                              'slot':number, 'task':name, 'task_id':fixtures[name]['task_id'],
                              'configuration':configuration,'rung':rung,'limits':limits,
                              'configuration_sha256':configuration_identity(profiles[configuration]),
                              'fixture_sha256':policy.digest(fixtures[name])})
    return cells, fixtures


def plan(profile, config):
    cells, fixtures = inventory(config)
    if configuration_identity(profile) not in {c['configuration_sha256'] for c in cells}:
        raise policy.CheckError('calibration.profile: active profile not in approved pair')
    if profile['campaign_root'] != config['profiles']['A']['campaign_root']:
        raise policy.CheckError('calibration.campaign: wrong campaign root')
    for value in config['profiles'].values():
        if value['campaign_root'] != profile['campaign_root']:
            raise policy.CheckError('calibration.campaign: both profiles must share calibration root')
        preflight.offline(value)
    return {'section':SECTION,'budget_version':VERSION,'evidence_kind':config['evidence_kind'],
            'admission_version':policy.ADMISSION_VERSION,'attempt_accounting':policy.ATTEMPT_ACCOUNTING,
            'scientific_credit':False,'implementation_version':IMPLEMENTATION_VERSION,
            'execution_authorized':bool(policy.campaign_activation(
                profile['campaign_root'], profile['campaign_id'],
                policy.METHODOLOGY_CALIBRATION)),
            'cells':cells,'fixtures':fixtures,'config':config,'software':runner.software_identity(),
            'ceilings':{'tokens':TOTAL_TOKENS,'turns':TOTAL_TURNS,'task_seconds':TASK_SECONDS,
                        'overhead_seconds':OVERHEAD_SECONDS,'all_seconds':ALL_SECONDS}}


def _load(campaign, *, recorded_finalized=False):
    target = section_path(campaign)
    saved = store.read_json(target/'run.json')
    sealed = recorded_finalized and (target/'manifest.json').exists()
    if sealed:
        reporting.verify_manifest(target)
    if not sealed:
        if saved.get('admission_version') != policy.ADMISSION_VERSION:
            raise policy.CheckError('calibration.historical: old unsealed accounting cannot resume prospectively')
        cells, fixtures = inventory(saved['config'])
        if saved['cells'] != cells or saved['fixtures'] != fixtures:
            raise policy.CheckError('calibration.identity: changed scientific inventory or fixture')
    if any(p['campaign_root'] != str(Path(campaign).resolve()) for p in saved['config']['profiles'].values()):
        raise policy.CheckError('calibration.campaign: wrong root')
    return target, saved


def _rows(target, saved):
    rows = {}
    for cell in saved['cells']:
        path = target/'evidence'/cell['id']
        children = sorted(p for p in path.iterdir() if p.is_dir() and not store.preparation_only(p)) if path.exists() else []
        if len(children) > 1:
            raise policy.CheckError('calibration.attempts: a consumed slot cannot have a replacement')
        values = store.attempts(target, cell['id'])
        if values and values[0].get('finalized'):
            score = values[0]
            if score.get('cell') != cell or score.get('scientific_credit') is not False:
                raise policy.CheckError('calibration.evidence: wrong cell/credit')
        rows[cell['id']] = values
    return rows


def status(campaign):
    target, saved = _load(campaign, recorded_finalized=True)
    if (target/'manifest.json').exists():
        reporting.verify_manifest(target)
    rows = _rows(target, saved)
    pending = [c for c in saved['cells'] if not rows[c['id']]]
    invalid = any(r and (not r[0].get('finalized') or r[0].get('outcome') == 'INVALID') for r in rows.values())
    stopped = (target/'stop.json').exists()
    state = 'BLOCKED' if stopped else 'INTERRUPTED' if pending else 'COMPLETED_PARTIAL' if invalid else 'COMPLETED'
    return {'section':SECTION,'state':state,'evidence_kind':saved['config']['evidence_kind'],
            'scientific_credit':False,'consumed_slots':sum(bool(v) for v in rows.values()),
            'next_cell':pending[0] if pending else None,
            'preparation_failures':store.preparation_failures(target),
            'units':{k:(v[0] if v else None) for k,v in rows.items()}}


class Deadline(agentic.TaskDeadline):
    pass


class Clock:
    """Phase and aggregate deadlines on the active CLI's owned call stack."""
    def __init__(self, target, task, started):
        self.target, self.task, self.started = target, task, started
        self.previous = None
        self.phase_name = None
        self.phases = []
        self.at = time.monotonic()
        self.deadline = None
        self.task_deadline = None
        self.old_handler = signal.getsignal(signal.SIGALRM)
        self.old_timer = signal.getitimer(signal.ITIMER_REAL)
        self.old_deadline = self.at + self.old_timer[0] if self.old_timer[0] else None
        signal.signal(signal.SIGALRM, self.expired)
    def expired(self, *_):
        raise Deadline(self.phase_name)
    def phase(self, name):
        now = time.monotonic()
        if self.phase_name:
            self.phases.append({'phase':self.phase_name,'seconds':now-self.at})
        self.phase_name, self.at = name, now
        bounds = {'admission':120,'setup':60,'task':self.task['limits']['wall_seconds'],
                  'checker':CHECKER_SECONDS[self.task['task']], 'termination':75}
        # Keep termination/owner handback time reserved even at aggregate cutoff.
        if name == 'termination':
            self.deadline = now + 75
        else:
            aggregate = ALL_SECONDS - (time.time()-self.started) - 255
            if aggregate <= 0:
                raise Deadline('aggregate')
            self.deadline = now + min(bounds[name], aggregate)
            if name == 'task':
                self.task_deadline = self.task_deadline or self.deadline
                self.deadline = self.task_deadline
        self.check()
        signal.setitimer(signal.ITIMER_REAL, max(1e-6, self.deadline - time.monotonic()))
        return self.deadline
    def check(self):
        if self.deadline is not None and time.monotonic() >= self.deadline:
            raise Deadline(self.phase_name)
    def close(self):
        signal.setitimer(signal.ITIMER_REAL, 0)
        if self.phase_name:
            self.phases.append({'phase':self.phase_name,'seconds':time.monotonic()-self.at})
        signal.signal(signal.SIGALRM, self.old_handler)
        if self.old_deadline is not None:
            signal.setitimer(signal.ITIMER_REAL,
                             max(0.0, self.old_deadline-time.monotonic()), self.old_timer[1])


def _charged(target, saved):
    """Reserve unknown in-flight generation at its cap, never invent native usage."""
    tokens = turns = task = overhead = 0
    for cell in saved['cells']:
        candidates = [p for p in (target/'evidence'/cell['id']).glob('*') if p.is_dir()]
        if not candidates:
            continue
        started_attempts = [p for p in candidates if not store.preparation_only(p)]
        if started_attempts:
            task += cell['limits']['wall_seconds']
        # One shared per-cell setup reservation, including failed preparation.
        overhead += 180+120+60+CHECKER_SECONDS[cell['task']]+75+60
        for base in candidates:
            if store.preparation_only(base) and (base/'phase-times.json').exists():
                phases = store.read_json(base/'phase-times.json')['phases']
                overhead += sum(phase['seconds'] for phase in phases)
            for path in base.glob('http-*-reservation.json'):
                reservation = store.read_json(path)
                receipt_path = path.with_name(path.name.replace('-reservation','-accounting'))
                receipt = store.read_json(receipt_path) if receipt_path.exists() else {}
                tokens += receipt.get('completion_tokens', reservation['max_tokens'])
                turns += 1
    return {'tokens':tokens,'turns':turns,'task_seconds':task,'overhead_seconds':overhead}


def _assert_cost(target, saved, started):
    charged = _charged(target, saved)
    if (charged['tokens'] > TOTAL_TOKENS or charged['turns'] > TOTAL_TURNS
            or charged['task_seconds'] > TASK_SECONDS
            or charged['overhead_seconds']+120 > OVERHEAD_SECONDS
            or not 0 <= time.time()-started <= ALL_SECONDS):
        raise policy.CheckError('calibration.aggregate: token/turn/time/phase envelope exhausted')
    return charged


def _stop(target, reason):
    reporting.ensure_json(target/'stop.json', {'reason':reason,'scientific_credit':False})


def _terminal(path, profile, cell, message, budget=False):
    facets = policy.derive_outcome('VALID' if budget else 'INVALID',
                                  'INCOMPLETE' if budget else 'NOT_APPLICABLE',
                                  'NOT_SCOREABLE' if budget else 'NOT_APPLICABLE',
                                  'BUDGET' if budget else 'NONE')
    return dict(facets, cell=cell, stop_reason=message, scientific_credit=False,
                evaluation={'checks':[], 'partial_progress':[]},
                profile_revision=policy.digest(profile),evidence_kind=profile['evidence_kind'])


def _commit(path, profile, cell, result):
    # Core files remain original even when a boundary deadline lost the return value.
    if not (path/'response.raw').exists():
        store.put(path/'response.raw', b'')
    result.update(cell=cell, calibration=True, scientific_credit=False, unit_id=cell['id'], attempt_id=path.name,
                  profile_revision=policy.digest(profile), evidence_kind=profile['evidence_kind'])
    if (path/'native-fatal.json').exists():
        result.update(fatal_device_condition=True, failure_class='DEVICE_RESOURCE')
    elif (path/'resource-failure.json').exists():
        result.update(fatal_device_condition=False,
                      failure_class=store.read_json(path/'resource-failure.json')['failure_class'])
    store.finalize_attempt(path, result, policy.METHODOLOGY_CALIBRATION)


def _interrupted(target, saved):
    for cell in saved['cells']:
        candidates = store.attempts(target, cell['id'])
        path = Path(candidates[0]['path']) if candidates else target/'absent'
        if path.exists() and not (path/'attempt.json').exists():
            conditions = path/'conditions.json'
            if conditions.exists():
                profile = store.read_json(conditions)['profile']
            else:
                # No exchange is allowed before these files exist. Preserve a
                # startup interruption without inventing a live-process binding.
                profile = saved['config']['profiles'][cell['configuration']]
                store.put_json(conditions, {'profile':profile,'profile_revision':policy.digest(profile),
                    'evidence_kind':profile['evidence_kind'],'request_limits':cell['limits'],
                    'preflight':{'echo':{}},'startup_binding_unrecorded':True,'scientific_credit':False})
            if not (path/'request.json').exists():
                store.put_json(path/'request.json', {'cell':cell,'generation_not_started':True})
            _commit(path, profile, cell, _terminal(path, profile, cell, 'INTERRUPTED_SLOT_CONSUMED'))


def run(profile, config, *, prepare=False):
    if config.get('evidence_kind') == 'CALIBRATION' and not policy.campaign_activation(
            profile.get('campaign_root'), profile.get('campaign_id'),
            policy.METHODOLOGY_CALIBRATION):
        raise policy.CheckError('calibration.authorization: this campaign is NOT authorized for live execution')
    package = plan(profile, config)
    campaign = Path(profile['campaign_root'])
    target = section_path(campaign)
    with store.locked(campaign):
        if (target/'manifest.json').exists():
            report(campaign)
            return status(campaign)
        if not (target/'run.json').exists():
            store.put_json(target/'run.json', package)
            store.put_json(target/'started.json', {'epoch':time.time(),'scientific_credit':False})
        target, saved = _load(campaign)
        if (saved['cells'] != package['cells'] or saved['fixtures'] != package['fixtures']
                or saved['config']['evidence_kind'] != config['evidence_kind']):
            raise policy.CheckError('calibration.config: scientific package already frozen')
        _interrupted(target, saved)
        if (target/'stop.json').exists():
            raise policy.CheckError('calibration.stop: prior attribution/safety/aggregate failure requires human review')
        started = store.read_json(target/'started.json')['epoch']
        try:
            _assert_cost(target, saved, started)
        except policy.CheckError:
            _stop(target, 'AGGREGATE_LIMIT');raise
        rows = _rows(target,saved)
        pending = [c for c in saved['cells'] if not rows[c['id']]]
        if not pending:
            if prepare:
                last = max(store.read_json(p)['finished_epoch'] for p in (target/'phases').glob('*.json'))
                if not 0 <= time.time()-last <= 60:
                    _stop(target,'TEARDOWN_LIMIT')
                    raise policy.CheckError('calibration.teardown: final owner handback interval exceeded')
                reporting.ensure_json(target/'ended.json', {'epoch':time.time(),
                    'meaning':'Execution envelope closed after operator-owned teardown; not independent GPU release proof'})
            return status(campaign)
        cell = pending[0]
        if configuration_identity(profile) != cell['configuration_sha256']:
            raise policy.CheckError('calibration.order: wrong deployment for next fixed slot')
        armed = target/'preparation'/f"{cell['slot']:02d}.json"
        if prepare:
            previous = list((target/'phases').glob('*.json')) if (target/'phases').exists() else []
            if previous:
                last = max(store.read_json(p)['finished_epoch'] for p in previous)
                if not 0 <= time.time()-last <= 60:
                    _stop(target,'TEARDOWN_LIMIT');raise policy.CheckError('calibration.teardown:60second owner handback interval exceeded')
            if not armed.exists():
                store.put_json(armed, {'epoch':time.time(), 'cell':cell})
            return dict(status(campaign), next_action='Owner prepares only the approved deployment within180seconds, then run/resume without --prepare')
        if not armed.exists():
            raise policy.CheckError('calibration.prepare: --prepare required BEFORE owned serving preparation')
        preparation = store.read_json(armed)
        if preparation['cell'] != cell or not 0 <= time.time()-preparation['epoch'] <= 180:
            _stop(target,'SERVING_PREPARATION_LIMIT');raise policy.CheckError('calibration.preparation:180second bound exceeded')
        path = store.new_attempt(target,cell['id'],preparing=True)
        store.put_json(path/'request.json', {'cell':cell,'fixture':saved['fixtures'][cell['task']]})
        store.put_json(path/'conditions.json', {'profile':profile,'profile_revision':policy.digest(profile),
            'evidence_kind':profile['evidence_kind'],'request_limits':cell['limits'],
            'preflight':{'echo':{}},'scientific_credit':False})
        clock = Clock(target,cell,started)
        result = None
        previous_sigint = signal.getsignal(signal.SIGINT)
        stop_requested = False
        def interrupted(*_):
            nonlocal stop_requested
            stop_requested = True
        signal.signal(signal.SIGINT,interrupted)
        try:
            clock.phase('admission')
            admission = preflight.online(profile)
            store.put_json(path/'admission.json',admission)
            def exchange(body, remaining):
                return exchange_turn(profile,body,remaining,path,target,saved,started,cell,
                                     clock=clock,stop_requested=lambda:stop_requested)
            result = agentic.execute(saved['fixtures'][cell['task']],cell['limits'],config['adapter'],
                                     exchange,path,stop_requested=lambda:stop_requested,phase=clock.phase)
            if result.get('interrupted'):
                result = _terminal(path,profile,cell,'INTERRUPTED_SLOT_CONSUMED')
        except Deadline as exc:
            result = _terminal(path,profile,cell,'DEADLINE_'+str(exc),budget=str(exc)=='task')
        except (policy.CheckError,OSError) as exc:
            result = _terminal(path,profile,cell,'ADMISSION_OR_RESOURCE: '+str(exc))
            evidence = getattr(exc, 'evidence', None)
            if evidence is not None:
                store.put_json(path/'admission-error.json', evidence)
        finally:
            clock.close()
            signal.signal(signal.SIGINT,previous_sigint)
            store.put_json(path/'quiescence.json',{'observations_drained':True,
                'stop_requested':stop_requested,'epoch':time.time(),
                'meaning':'Synchronous collectors have returned; owner must await CLI exit before teardown'})
            store.put_json(path/'phase-times.json',{'phases':clock.phases,'finished_epoch':time.time()})
        _commit(path,profile,cell,result)
        if store.preparation_only(path):
            return dict(status(campaign), preparation_error=result.get('stop_reason'),
                        next_action='Correct environment within the original bounded setup window; no model trial consumed')
        store.put_json(target/'phases'/f"{cell['slot']:02d}.json",{'finished_epoch':time.time(),'cell':cell})
        if result['outcome']=='INVALID' and result.get('stop_reason') != 'INTERRUPTED_SLOT_CONSUMED':
            _stop(target,'INVALID_ATTRIBUTION_OR_HARNESS')
        _assert_cost(target,saved,started)
        return status(campaign)


def exchange_turn(profile, body, remaining, path, target, saved, started, cell, *,
                  clock=None, stop_requested=lambda:False):
    began = time.monotonic()
    deadline = clock.task_deadline if clock is not None else began + remaining
    def check_time():
        if time.monotonic() >= deadline:
            raise Deadline('task')
    check_time()
    if stop_requested():
        raise KeyboardInterrupt
    request = {**body,'model':profile['runtime']['serve']['model_id'],'stream':False,
               **policy.sampling_settings(profile),**profile['reasoning']['controls'],'return_tokens':True}
    n = len(list(path.glob('http-*-request.json')))+1
    prefix = f'http-{n:04d}'
    store.put_json(path/(prefix+'-request.json'),request)
    try:
        meter = context.measure_native_request(profile,request,deadline=deadline)
    except Exception as exc:
        check_time()
        store.put_json(path/(prefix+'-meter-error.json'),{'error':str(exc)})
        return {'raw':b'', 'calibration_stop':'HARNESS_FAILURE','error':'native context meter unavailable'}
    check_time()
    store.put_json(path/(prefix+'-context.json'),meter)
    cap = request.get('max_tokens')
    if type(cap) is not int or not 0 < cap <= cell['limits']['max_tokens']:
        return {'raw':b'','calibration_stop':'HARNESS_FAILURE','error':'per-response cap substituted'}
    if meter['input_tokens'] > INPUT_CAP or meter['input_tokens']+cap > profile['runtime']['context_capacity']:
        return {'raw':b'','calibration_stop':'HARNESS_FAILURE' if n==1 else 'CONTEXT_LIMIT',
                'error':'initial geometry invalid' if n==1 else 'original conversation exhausted context budget'}
    charged = _assert_cost(target,saved,started)
    used = sum(store.read_json(p).get('completion_tokens',0) for p in path.glob('http-*-accounting.json'))
    if used+cap > cell['limits']['total_tokens'] or charged['tokens']+cap > TOTAL_TOKENS or charged['turns']>=TOTAL_TURNS:
        return {'raw':b'','calibration_stop':'HARNESS_FAILURE','error':'generation reservation exceeds approved envelope'}
    check_time()
    if stop_requested():
        raise KeyboardInterrupt
    timeout = min(180, deadline-time.monotonic())
    store.put_json(path/(prefix+'-reservation.json'),{'max_tokens':cap,'epoch':time.time()})
    store.generation_intent(path, request)
    observation = runner._http_exchange(profile,request,timeout)
    raw = observation.get('raw',b'')
    store.put(path/(prefix+'-response.raw'),raw)
    store.put_json(path/(prefix+'-conditions.json'),{k:v for k,v in observation.items() if k!='raw'})
    if runner._fatal_condition(
            raw, observation.get('error'), runner.reconstruct_response(raw)['envelope'] or {}):
        store.put_json(path/'native-fatal.json',{'fatal':True,'source':prefix+'-response.raw'})
    if observation.get('error') or observation.get('status') != 200:
        return observation
    envelope = runner.reconstruct_response(raw)['envelope'] or {}
    usage = envelope.get('usage') or {}
    identity = envelope.get('model') == request['model']
    valid = diagnostic.native_accounting(envelope,cap)
    valid = valid and type(usage.get('prompt_tokens')) is int and usage['prompt_tokens']==meter['input_tokens']
    valid = valid and (envelope.get('__verbose') or {}).get('truncated') is False
    if not valid or not identity:
        return {'raw':raw,'status':200,'calibration_stop':'HARNESS_FAILURE','error':'native accounting/context/attribution contradiction'}
    store.put_json(path/(prefix+'-accounting.json'),{'completion_tokens':usage['completion_tokens'],
                                                    'input_tokens':meter['input_tokens']})
    if time.monotonic() >= deadline:
        observation.update(timed_out=True,error='task deadline exhausted after generation')
    if stop_requested():
        raise KeyboardInterrupt
    return observation


def resume(campaign, profile=None, *, prepare=False):
    target,saved = _load(campaign)
    if (target/'manifest.json').exists():
        report(campaign);return status(campaign)
    if profile is None:
        raise policy.CheckError('calibration.resume: fresh --profile binding required')
    return run(profile,saved['config'],prepare=prepare)


def report(campaign):
    target,saved = _load(campaign, recorded_finalized=True)
    if (target/'manifest.json').exists():
        # Preserve the recorded implementation's finalized conclusions; do not
        # rerun task/oracle evaluation under repaired execution semantics.
        state = status(campaign)
        receipt = store.read_json(target/'validation.json')
        expected = {'section':SECTION,'disposition':'PASS','state':state['state'],
            'evidence_kind':saved['config']['evidence_kind'],'scientific_credit':False,
            'consumed_slots':state['consumed_slots'],
            'results':{key:{'outcome':value['outcome'],'reason':value.get('reason'),
                'partial_progress':value.get('evaluation',{}).get('partial_progress',[]),
                'scientific_credit':False} for key,value in state['units'].items() if value},
            'charged':_charged(target,saved),'budget_version':saved['budget_version']}
        if receipt != expected:
            raise policy.CheckError('calibration.historical: recorded validation does not match committed attempts')
        return receipt
    rows = _rows(target,saved)
    state = status(campaign)
    if state['next_cell'] is not None and not (target/'stop.json').exists():
        raise policy.CheckError('calibration.report: unexecuted slots remain; no premature completion claim')
    ended = target/'ended.json'
    if not (target/'stop.json').exists() and not ended.exists():
        raise policy.CheckError('calibration.report: close final teardown envelope with resume --prepare first')
    if ended.exists():
        elapsed = store.read_json(ended)['epoch']-store.read_json(target/'started.json')['epoch']
        if not 0 <= elapsed <= ALL_SECONDS:
            raise policy.CheckError('calibration.report: aggregate deadline exceeded')
    charged = _charged(target,saved)
    if any(charged[k] > v for k,v in (
            ('tokens',TOTAL_TOKENS),('turns',TOTAL_TURNS),('task_seconds',TASK_SECONDS),
            ('overhead_seconds',OVERHEAD_SECONDS-120))):
        raise policy.CheckError('calibration.report: aggregate cost envelope exceeded')
    results = {}
    for cell in saved['cells']:
        values = rows[cell['id']]
        if not values:
            continue
        score = values[0]
        if not score.get('finalized'):
            raise policy.CheckError('calibration.report: interrupted slot must be consumed by resume first')
        path = Path(score['path'])
        profile = store.read_json(path/'conditions.json')['profile']
        if configuration_identity(profile)!=cell['configuration_sha256']:
            raise policy.CheckError('calibration.report: deployment substitution')
        if (path/'admission.json').exists():
            policy.validate_echo(profile,store.read_json(path/'admission.json')['echo'])
        if (path/'agentic-result.json').exists() and score.get('stop_reason') not in ('INTERRUPTED_SLOT_CONSUMED',):
            replay = agentic.replay(path,saved['fixtures'][cell['task']],cell['limits'],saved['config']['adapter'])
            if replay['outcome'] != score['outcome'] or replay['facets'] != score['facets']:
                raise policy.CheckError('calibration.report: original Agentic reconstruction disagrees')
        for request_path in sorted(path.glob('http-*-request.json')):
            prefix = request_path.name.removesuffix('-request.json')
            request = store.read_json(request_path)
            core_request_path = path/('agentic-'+prefix+'-request.json')
            if core_request_path.exists():
                core = store.read_json(core_request_path)
                if any(request.get(k)!=v for k,v in core.items()):
                    raise policy.CheckError('calibration.report: original core request changed')
            core_raw = path/('agentic-'+prefix+'-response.raw')
            parent_raw = path/(prefix+'-response.raw')
            if core_raw.exists() and parent_raw.exists() and core_raw.read_bytes() != parent_raw.read_bytes():
                raise policy.CheckError('calibration.report: original core/transport bytes disagree')
            expected = {'model':profile['runtime']['serve']['model_id'],'stream':False,
                        **policy.sampling_settings(profile),**profile['reasoning']['controls'],
                        'return_tokens':True}
            if any(request.get(k)!=v for k,v in expected.items()):
                raise policy.CheckError('calibration.report: original settings changed')
            if not 0 < request['max_tokens'] <= cell['limits']['max_tokens']:
                raise policy.CheckError('calibration.report: response cap changed')
            meter_path = path/(prefix+'-context.json')
            if meter_path.exists():
                meter = store.read_json(meter_path)
                payload = meter['render_request']
                if (meter['request_sha256']!=policy.digest(request) or payload['messages']!=request['messages']
                        or payload.get('tools')!=request.get('tools')
                        or any(payload.get(k)!=v for k,v in profile['reasoning']['controls'].items())
                        or meter['input_tokens']!=len(meter['tokenize_response']['tokens'])):
                    raise policy.CheckError('calibration.report: native meter/tool binding changed')
            accounting = path/(prefix+'-accounting.json')
            if accounting.exists():
                env = runner.reconstruct_response((path/(prefix+'-response.raw')).read_bytes())['envelope'] or {}
                count = (env.get('usage') or {}).get('completion_tokens')
                if (not diagnostic.native_accounting(env,request['max_tokens'])
                        or store.read_json(accounting) != {'completion_tokens':count,'input_tokens':meter['input_tokens']}
                        or (env.get('usage') or {}).get('prompt_tokens') != meter['input_tokens']
                        or (env.get('__verbose') or {}).get('truncated') is not False
                        or env.get('model') != request['model']
                        or meter['input_tokens'] > INPUT_CAP
                        or meter['input_tokens']+request['max_tokens'] > profile['runtime']['context_capacity']):
                    raise policy.CheckError('calibration.report: native accounting/geometry/identity changed')
        results[cell['id']]={'outcome':score['outcome'],'reason':score.get('reason'),
                             'partial_progress':score.get('evaluation',{}).get('partial_progress',[]),
                             'scientific_credit':False}
    receipt = {'section':SECTION,'disposition':'PASS','state':state['state'],
               'evidence_kind':saved['config']['evidence_kind'],'scientific_credit':False,
               'consumed_slots':state['consumed_slots'],'results':results,
               'charged':charged,'budget_version':VERSION}
    reporting.ensure_json(target/'validation.json',receipt)
    text = ('# WELP — non-scored Agentic calibration\n\n'
            'No scientific advancement/readiness credit.\n\n```json\n'+json.dumps(receipt,indent=2)+'\n```\n').encode()
    text_path = target/'SECTION-REPORT.md'
    if text_path.exists():
        if text_path.read_bytes() != text:
            raise policy.CheckError('calibration.report: refusing report rewrite')
    else:
        store.put(text_path,text)
    reporting.ensure_json(target/'manifest.json', {'files':{str(p.relative_to(target)):policy.file_sha(p)
        for p in sorted(target.rglob('*')) if p.is_file() and p.name!='manifest.json'}})
    return receipt
