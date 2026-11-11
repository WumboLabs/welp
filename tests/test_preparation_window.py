"""Preparation setup-window semantics (corrected 2026-11-09): the 180-second
deadline bounds the CURRENT setup-retry streak (measured from the latest
preparation-only failure), so a legitimate resume after environment repair
can make one fresh setup attempt, while rapid flapping stays bounded."""
import json
import time
import unittest
from pathlib import Path

from welp_next import policy, store


class PreparationWindow(unittest.TestCase):
    def setUp(self):
        self.root = Path(policy.PROJECT_ROOT) / 'tmp' / 'm1-consumer-tests'
        self.section = self.root / f'prep-window-{int(time.time())}'
        self.section.mkdir(parents=True, exist_ok=True)
        self.addCleanup(self._cleanup)

    def _cleanup(self):
        import shutil
        shutil.rmtree(self.section, ignore_errors=True)

    def _seed_failure(self, unit, number, age_seconds):
        path = self.section / 'evidence' / unit / f'{number:04d}'
        path.mkdir(parents=True, exist_ok=True)
        (path / 'trial-boundary.json').write_text(json.dumps(
            {'accounting': policy.ATTEMPT_ACCOUNTING, 'epoch': time.time() - age_seconds}))
        return path

    def test_stale_streak_allows_one_fresh_setup_attempt(self):
        # a transient warmup failure 241 s ago no longer locks the unit:
        # the repaired environment gets one fresh setup attempt
        self._seed_failure('u-ctx', 1, 241)
        path = store.new_attempt(self.section, 'u-ctx', preparing=True)
        self.assertTrue((path / 'trial-boundary.json').exists())

    def test_rapid_streak_still_bounded_within_window(self):
        # rapid retries within the window remain allowed exactly as before
        # (bounded by the three-failure limit), never permanently extended
        self._seed_failure('u-flap', 1, 60)
        path = store.new_attempt(self.section, 'u-flap', preparing=True)
        self.assertTrue((path / 'trial-boundary.json').exists())
        # the streak cannot quietly extend forever: once the streak has both
        # started beyond the window and is still active, it fails closed
        stale_start = self.section / 'evidence' / 'u-stale' / '0001'
        stale_start.mkdir(parents=True, exist_ok=True)
        (stale_start / 'trial-boundary.json').write_text(json.dumps(
            {'accounting': policy.ATTEMPT_ACCOUNTING, 'epoch': time.time() - 300}))
        (stale_start / 'generation-0001-intent.json').write_text('{}')  # real trial: not preparation-only
        self._seed_failure('u-stale', 2, 200)  # streak started beyond the window
        self._seed_failure('u-stale', 3, 20)   # ...and is still active
        with self.assertRaises(policy.CheckError) as ctx:
            store.new_attempt(self.section, 'u-stale', preparing=True)
        self.assertIn('setup-retry streak', str(ctx.exception))

    def test_three_failure_limit_still_fail_closed(self):
        for number in (1, 2, 3):
            self._seed_failure('u-limit', number, 300 * number)
        with self.assertRaises(policy.CheckError) as ctx:
            store.new_attempt(self.section, 'u-limit', preparing=True)
        self.assertIn('three setup failures', str(ctx.exception))

    def test_dispatched_attempts_never_count_as_preparation(self):
        # an attempt with a dispatched generation intent is a real model
        # trial: it is neither preparation-only nor bounded by this window
        self._seed_failure('u-real', 1, 241)
        path = store.new_attempt(self.section, 'u-real', preparing=True)
        store.generation_intent(path, {'messages': [{'role': 'user', 'content': 'x'}]})
        self.assertFalse(store.preparation_only(path))
        # another unit's window is unaffected by the dispatched trial
        self._seed_failure('u-other', 1, 241)
        store.new_attempt(self.section, 'u-other', preparing=True)


if __name__ == '__main__':
    unittest.main()
