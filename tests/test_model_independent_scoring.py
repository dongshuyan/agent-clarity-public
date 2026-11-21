"""Hook-to-title regressions for models without a usable context-window entry."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'plugins/clarity-session-titles/scripts'))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_titles import FakeRPC  # noqa: E402
import session_score  # noqa: E402
from title_runtime import TitleManager  # noqa: E402


class ModelIndependentScoringTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name) / 'codex-home'
        self.home.mkdir()
        self.env = patch.dict(os.environ, {'CODEX_HOME': str(self.home)})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.root = Path(self.temp.name).resolve() / 'project'
        self.root.mkdir()
        subprocess.run(['git', 'init', '-q', str(self.root)], check=True)
        session_score.activate(self.root, now=100)
        session_score.configure(self.root, level='S2', window_mode='reference')
        self.rpc = FakeRPC(self.root)
        TitleManager(self.root, self.rpc, caller_thread_id='test-thread').set(
            'test-thread', '原始需求', '讨论中', self.root, progress='开始工作')
        self.transport = patch.object(
            session_score, 'CodexRPC',
            side_effect=lambda **kwargs: session_score.nullcontext(self.rpc))
        self.transport.start()
        self.addCleanup(self.transport.stop)

    def event(self, name, turn='turn-1', **fields):
        return session_score.handle_payload(self.root, {
            'cwd': str(self.root), 'session_id': 'test-thread', 'turn_id': turn,
            'model': 'unlisted-model', 'hook_event_name': name, **fields,
        })

    def completed_request(self, turn='turn-1', **fields):
        return self.event('PostModelRequest', turn, **{
            'status': 'completed', 'token_usage': {'input_tokens': 760}, **fields,
        })

    def result(self):
        return session_score.read_score_state(self.root, 'test-thread')['score_result']

    def assert_baseline(self, result, score):
        self.assertEqual(result['level'], 'S2')
        self.assertEqual(result['score_status'], 'insufficient_data')
        self.assertIsNone(result['score'])
        self.assertEqual(result.get('baseline'), {'level': 'S1', 'score': score})
        self.assertEqual(self.rpc.thread['name'].split('｜', 1)[0],
                         f'S1·{score}分（窗口未知）')

    def assert_no_baseline(self, result, level='S2'):
        self.assertEqual(result['level'], level)
        self.assertEqual(result['score_status'], 'insufficient_data')
        self.assertIsNone(result['score'])
        self.assertIsNone(result.get('baseline'))
        self.assertEqual(self.rpc.thread['name'].split('｜', 1)[0], '未评分')

    def test_unknown_model_keeps_s2_unscored_and_displays_separate_s1_baseline(self):
        self.assertEqual(self.event('UserPromptSubmit'), {})
        self.completed_request()
        self.event('Stop')
        self.assert_baseline(self.result(), 2)
        writes = len(self.rpc.writes)
        self.assertEqual(self.event('Stop'), {})
        self.assert_baseline(self.result(), 2)
        self.assertEqual(len(self.rpc.writes), writes)

    def test_catalog_repair_restores_s2_next_turn_without_resetting_the_chat(self):
        self.event('UserPromptSubmit')
        self.completed_request()
        self.event('Stop')
        first = self.result()
        (self.home / 'models_cache.json').write_text(json.dumps({'models': [{
            'slug': 'unlisted-model', 'context_window': 1000,
            'effective_context_window_percent': 100,
        }]}))

        self.event('UserPromptSubmit', 'turn-2')
        self.completed_request('turn-2')
        self.event('Stop', 'turn-2')
        restored = self.result()
        self.assertEqual(restored['level'], 'S2')
        self.assertEqual(restored['score_status'], 'scored')
        self.assertIsInstance(restored['score'], int)
        self.assertIsNone(restored.get('baseline'))
        self.assertEqual(self.rpc.thread['name'].split('｜', 1)[0],
                         f"S2·{restored['score']}分")
        self.assertEqual(session_score.read_score_state(self.root, 'test-thread')
                         ['metrics']['round_count'], 2)
        self.assertEqual(first['score_status'], 'insufficient_data')
        self.assertEqual(first.get('baseline'), {'level': 'S1', 'score': 2})

    def test_s1_never_resolves_a_window_or_reads_a_catalog_or_injects_a_probe(self):
        session_score.configure(self.root, level='S1', window_mode='reference')
        with patch.object(session_score, 'resolve_window',
                          wraps=session_score.resolve_window) as resolve, \
                patch.object(session_score, '_read_reference_file',
                             wraps=session_score._read_reference_file) as read:
            for index in range(1, 7):
                turn = f'turn-{index}'
                self.assertEqual(self.event('UserPromptSubmit', turn), {})
                self.completed_request(turn)
                self.event('Stop', turn)
        resolve.assert_not_called()
        read.assert_not_called()
        result = self.result()
        self.assertEqual(result['level'], 'S1')
        self.assertEqual(result['score_status'], 'scored')
        self.assertIsNone(result.get('baseline'))
        self.assertNotIn('窗口未知', self.rpc.thread['name'])

    def test_strict_mode_does_not_publish_a_baseline_for_a_valid_input_sample(self):
        session_score.configure(self.root, window_mode='actual_only')
        self.event('UserPromptSubmit')
        self.completed_request()
        self.event('Stop')
        self.assert_no_baseline(self.result())

    def test_invalid_or_unsuccessful_latest_request_cannot_keep_an_earlier_baseline(self):
        cases = (
            {'token_usage': {}},
            {'token_usage': {'input_tokens': True}},
            {'token_usage': {'input_tokens': -1}},
            {'status': 'failed'},
            {'status': 'cancelled'},
        )
        for index, fields in enumerate(cases, 1):
            with self.subTest(fields=fields):
                turn = f'turn-{index}'
                self.event('UserPromptSubmit', turn)
                self.completed_request(turn)
                self.completed_request(turn, **fields)
                self.event('Stop', turn)
                self.assert_no_baseline(self.result())

    def test_new_turn_without_a_request_does_not_reuse_a_previous_baseline(self):
        self.event('UserPromptSubmit')
        self.completed_request()
        self.event('Stop')
        self.event('UserPromptSubmit', 'turn-2')
        self.event('Stop', 'turn-2')
        self.assert_no_baseline(self.result())

    def test_compaction_without_a_fresh_request_removes_baseline_eligibility(self):
        self.event('UserPromptSubmit')
        self.completed_request()
        self.event('PreCompact')
        self.completed_request()  # The summary request is not a fresh sample.
        self.event('PostCompact')
        self.event('Stop')
        self.assert_no_baseline(self.result())

    def assert_probe_failure_does_not_publish_baseline(self, level, probe_round):
        session_score.configure(self.root, level=level)
        for index in range(1, probe_round + 1):
            turn = f'turn-{index}'
            prompt = self.event('UserPromptSubmit', turn, prompt='继续当前工作')
            self.completed_request(turn)
            self.event('Stop', turn)
        self.assertIn('hookSpecificOutput', prompt)
        self.assert_no_baseline(self.result(), level=level)
        state = session_score.read_score_state(self.root, 'test-thread')
        self.assertEqual(state['last_probe']['turn_id'], f'turn-{probe_round}')
        self.assertEqual(state['last_probe']['score_status'], 'insufficient_data')

    def test_s3_actual_probe_failure_cannot_be_hidden_by_a_baseline(self):
        self.assert_probe_failure_does_not_publish_baseline('S3', 3)

    def test_s4_actual_probe_failure_cannot_be_hidden_by_a_baseline(self):
        self.assert_probe_failure_does_not_publish_baseline('S4', 5)

    def test_s4_non_probe_turn_can_display_a_baseline(self):
        session_score.configure(self.root, level='S4')
        self.assertEqual(self.event('UserPromptSubmit', prompt='继续当前工作'), {})
        self.completed_request()
        self.event('Stop')
        self.assert_baseline(self.result(), 2)

    def test_a_high_s1_baseline_does_not_trigger_the_s2_semantic_threshold(self):
        for index in range(1, 33):
            self.event('UserPromptSubmit', f'turn-{index}')
        self.completed_request('turn-32')
        self.event('Stop', 'turn-32')
        previous = self.result()
        session_score.configure(self.root, level='S4')
        # Round 33 is not a periodic S4 probe; S1's 60 must not act as S2's 60.
        self.assertEqual(self.event('UserPromptSubmit', 'turn-33'), {})
        state = session_score.read_score_state(self.root, 'test-thread')
        self.assertIsNone(state.get('pending_probe'))
        self.assertFalse(state.get('threshold_probe_consumed', False))
        self.assertEqual(previous['level'], 'S2')
        self.assertEqual(previous['score_status'], 'insufficient_data')
        self.assertIsNone(previous['score'])
        self.assertEqual(previous.get('baseline'), {'level': 'S1', 'score': 60})


if __name__ == '__main__':
    unittest.main()
