"""Invoke from the source workspace: python -m welp_next <command>."""
import argparse
import json
from pathlib import Path
import sys

from . import calibration, capability, diagnostic, m3, policy, preflight, reporting, runner, store


def _with_guidance(value):
    """Attach the derived advisory capability profile to any value carrying
    the m3.decisions envelope. Pure extension; absent decisions stay absent."""
    if isinstance(value, dict) and isinstance(value.get('advancement'), dict):
        value['capability_guidance'] = capability.guidance(value['advancement'])
    return value


def parser():
    cli = argparse.ArgumentParser(prog='welp', description='WELP Model and offline Agentic evaluation CLI')
    commands = cli.add_subparsers(dest='command', required=True)
    for name in ('plan', 'run', 'status', 'resume', 'report', 'validate'):
        sub = commands.add_parser(name)
        sub.add_argument('--json', action='store_true', help='compact machine-readable JSON')
        if name == 'validate':
            sub.add_argument('--campaign', required=True, action='append', type=Path,
                             help='finalized campaign directory; repeat for release aggregation')
        if name in ('plan', 'run'):
            sub.add_argument('--profile', required=True, type=Path)
            # Default is profile-specific: M1 -> reliability, M2 -> baseline.
            # A part that contradicts the profile pin is rejected, never silently
            # narrowed (M2 + --part reliability) or widened (M1 + --part baseline).
            sub.add_argument('--part', choices=list(runner.PARTS), default=None)
        elif name in ('status', 'resume', 'report'):
            sub.add_argument('--campaign', required=True, type=Path)
        if name == 'resume':
            sub.add_argument('--profile', type=Path, help='current compatible deployment conditions')
        if name in ('run', 'resume'):
            sub.add_argument('--prepare', action='store_true', help='arm the next calibration preparation clock; no generation')
        sub.add_argument('--section', choices=['baseline', 'diagnostic', 'calibration',
                                              'coding', 'advanced-reasoning',
                                              'advanced-long-context',
                                              'advanced-tool-use', 'helicopterbench',
                                              'runtime-performance',
                                              *m3.SECTIONS],
                         default=None if name in ('status', 'report') else 'baseline')
        if name in ('plan', 'run'):
            sub.add_argument('--agentic-config', type=Path,
                             help='explicit per-task SOFTWARE_TEST configuration; no live model execution')
            sub.add_argument('--calibration-config', type=Path, help='fixed non-scored calibration pair and budget version')
        if name in ('plan', 'status', 'report'):
            sub.add_argument('--advancement-inputs', type=Path,
                             help='versioned witness, scheduling and exploratory inputs; caller rules/approval/prerequisites rejected')
        if name in ('plan', 'run', 'status', 'resume', 'report'):
            sub.add_argument('--scored', action='store_true',
                             help='campaign-gated authentic scored Agentic route (agentic/3); '
                                  'inactive without the recorded campaign activation')
        if name == 'report':
            sub.add_argument('--reviews', type=Path, default=None,
                             help='optional recorded review records for section finalization')
    return cli


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if args.command == 'validate':
            from . import release_validation
            value = release_validation.release_readiness(
                args.campaign) if len(args.campaign) > 1 else \
                release_validation.validate_campaign(args.campaign[0])
            print(json.dumps(value, ensure_ascii=False, sort_keys=True,
                             indent=None if args.json else 2))
            records = value.get('validated_campaigns', [value])
            return 0 if all(r['all_finalized_sections_verified'] for r in records) else 2
        if getattr(args, 'scored', False):
            from . import scored
            if args.section not in m3.SECTIONS:
                raise policy.CheckError('scored.section: scored route serves the Agentic sections')
            if (getattr(args, 'part', None) or getattr(args, 'agentic_config', None)
                    or getattr(args, 'calibration_config', None)
                    or getattr(args, 'advancement_inputs', None)
                    or getattr(args, 'reviews', None)):
                raise policy.CheckError('scored.scope: no Model, offline, calibration, advancement or review inputs')
            if args.command in ('plan', 'run'):
                profile = preflight.load_profile(args.profile)
                config = store.read_json(
                    Path(args.profile).with_name('scored-agentic-config.json'))
                value = (scored.plan(profile, args.section, config) if args.command == 'plan'
                         else scored.run(profile, args.section, config))
            elif args.command == 'status':
                value = scored.status(args.campaign, args.section)
            elif args.command == 'resume':
                value = scored.resume(args.campaign, args.section,
                                      preflight.load_profile(args.profile) if args.profile else None)
            else:
                value = scored.report_section(args.campaign, args.section)
            print(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=None if args.json else 2))
            return 130 if args.command in ('run', 'resume') and value.get('state') == 'INTERRUPTED' else 0
        if args.section in ('coding', 'advanced-reasoning', 'advanced-long-context',
                            'advanced-tool-use', 'helicopterbench',
                            'runtime-performance'):
            if args.section == 'coding':
                from . import coding as section
                scope = 'coding.scope'
            elif args.section == 'advanced-reasoning':
                from . import advanced_reasoning as section
                scope = 'reasoning.scope'
            elif args.section == 'advanced-long-context':
                from . import long_context as section
                scope = 'long_context.scope'
            elif args.section == 'advanced-tool-use':
                from . import advanced_tool_use as section
                scope = 'tool_use.scope'
            elif args.section == 'runtime-performance':
                from . import runtime_performance as section
                scope = 'runtime_performance.scope'
            else:
                from . import helicopterbench as section
                scope = 'helicopterbench.scope'
            if (getattr(args, 'part', None) or getattr(args, 'agentic_config', None)
                    or getattr(args, 'calibration_config', None)
                    or getattr(args, 'advancement_inputs', None)
                    or getattr(args, 'reviews', None)
                    or getattr(args, 'scored', False)):
                raise policy.CheckError(f'{scope}: no offline, calibration, advancement or review inputs')
            if args.command == 'plan':
                value = section.plan(preflight.load_profile(args.profile))
            elif args.command == 'run':
                value = section.run(preflight.load_profile(args.profile))
            elif args.command == 'status':
                value = section.status(args.campaign)
            elif args.command == 'resume':
                value = section.resume(args.campaign,
                                       preflight.load_profile(args.profile) if args.profile else None)
            else:
                value = section.report_section(args.campaign)
            print(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=None if args.json else 2))
            return 130 if args.command in ('run', 'resume') and value.get('state') == 'INTERRUPTED' else 0
        if args.section == 'calibration':
            if (getattr(args, 'part', None) or getattr(args, 'agentic_config', None) or
                    getattr(args, 'advancement_inputs', None) or getattr(args, 'reviews', None) or
                    getattr(args, 'scored', False)):
                raise policy.CheckError('calibration.scope: no Model, readiness, advancement or review inputs')
            if args.command in ('plan', 'run'):
                if args.calibration_config is None:
                    raise policy.CheckError('calibration.config: --calibration-config required')
                profile = preflight.load_profile(args.profile)
                config = store.read_json(args.calibration_config)
                value = calibration.plan(profile, config) if args.command == 'plan' else calibration.run(profile, config, prepare=args.prepare)
            elif args.command == 'status':
                value = calibration.status(args.campaign)
            elif args.command == 'resume':
                profile = preflight.load_profile(args.profile) if args.profile else None
                value = calibration.resume(args.campaign, profile, prepare=args.prepare)
            else:
                value = calibration.report(args.campaign)
            print(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=None if args.json else 2))
            return 130 if args.command in ('run','resume') and value.get('state') == 'INTERRUPTED' else 0
        if getattr(args, 'calibration_config', None) or getattr(args, 'prepare', False):
            raise policy.CheckError('calibration.scope: calibration options require --section calibration')
        if args.section == 'diagnostic':
            if (getattr(args, 'part', None) or getattr(args, 'agentic_config', None) or
                    getattr(args, 'advancement_inputs', None) or getattr(args, 'reviews', None) or
                    getattr(args, 'scored', False)):
                raise policy.CheckError('diagnostic.scope: no Model, Agentic, advancement or review inputs')
            if args.command in ('plan', 'run'):
                profile = preflight.load_profile(args.profile)
                value = diagnostic.plan(profile) if args.command == 'plan' else diagnostic.run(profile)
            elif args.command == 'status':
                value = diagnostic.status(args.campaign)
            elif args.command == 'resume':
                value = diagnostic.resume(args.campaign, preflight.load_profile(args.profile) if args.profile else None)
            else:
                value = diagnostic.report(args.campaign)
        elif args.command in ('plan', 'run'):
            profile = preflight.load_profile(args.profile)
            if args.section in m3.SECTIONS:
                if args.agentic_config is None or args.part is not None:
                    raise policy.CheckError('agentic.config: --agentic-config required; --part is Model-only')
                config = store.read_json(args.agentic_config)
                value = (m3.plan(profile, args.section, config) if args.command == 'plan'
                         else m3.run(profile, args.section, config))
            else:
                if args.agentic_config:
                    raise policy.CheckError('agentic.config: select an Agentic section')
                value = (runner.plan(profile, args.part) if args.command == 'plan'
                         else runner.run(profile, args.part))
            if args.command == 'plan' and args.advancement_inputs:
                value['advancement'] = m3.decisions(profile['campaign_root'],
                    store.read_json(args.advancement_inputs))
                value = _with_guidance(value)
        elif args.command == 'status':
            if args.section in m3.SECTIONS:
                target = m3.section_path(args.campaign, args.section)
                if (target / 'manifest.json').exists():
                    reporting.verify_manifest(target)
                value = m3.status(args.campaign, args.section)
            else:
                if (store.section_path(args.campaign) / 'manifest.json').exists():
                    reporting.verify_manifest(store.section_path(args.campaign))
                value = runner.status(args.campaign)
                if args.advancement_inputs:
                    value['advancement'] = m3.decisions(args.campaign,
                        store.read_json(args.advancement_inputs))
                    value = _with_guidance(value)
        elif args.command == 'resume':
            if args.section in m3.SECTIONS:
                value = m3.resume(args.campaign, args.section, preflight.load_profile(args.profile) if args.profile else None)
            else:
                profile = (preflight.load_profile(args.profile) if args.profile else
                           store.read_json(store.section_path(args.campaign) / 'profile.json'))
                if Path(profile['campaign_root']).resolve() != args.campaign.resolve():
                    raise policy.CheckError('recovery.campaign_root: wrong campaign')
                value = runner.run(profile)
        else:
            if args.reviews and args.section in m3.SECTIONS:
                raise policy.CheckError('agentic.reviews: these fixtures use deterministic independent checks')
            value = (m3.report_section(args.campaign, args.section) if args.section in m3.SECTIONS
                     else reporting.report_section(args.campaign, reviews=args.reviews)
                     if args.section else reporting.report_campaign(args.campaign))
            if args.advancement_inputs:
                value['advancement'] = m3.decisions(args.campaign,
                    store.read_json(args.advancement_inputs), persist=True)
                value = _with_guidance(value)
        print(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=None if args.json else 2))
        return 130 if args.command in ('run', 'resume') and value.get('state') == 'INTERRUPTED' else 0
    except (policy.CheckError, OSError) as exc:
        print(json.dumps({'disposition': 'BLOCKED', 'check': str(exc)}, sort_keys=True))
        return 2
    except KeyboardInterrupt:
        print(json.dumps({'disposition': 'INTERRUPTED', 'reason': 'SIGINT before measurement'}))
        return 130


if __name__ == '__main__':
    sys.exit(main())
