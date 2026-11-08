import copy
import json
import re
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'plugins/clarity-session-titles/scripts'))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_titles import FakeRPC  # noqa: E402
import session_score  # noqa: E402
from title_runtime import TitleManager  # noqa: E402


class SessionScoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {'CODEX_HOME': str(Path(self.temp.name) / 'codex-home')})
        self.env.start()
        self.root = Path(self.temp.name).resolve() / 'project'
        self.root.mkdir()
        subprocess.run(['git', 'init', '-q', str(self.root)], check=True)
        session_score.activate(self.root, now=100)

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def test_s1_is_deterministic_and_uses_only_zero_model_signals(self):
        metrics = session_score.default_metrics()
        metrics.update(round_count=20, compression_observed=True, compression_count=1)
        first = session_score.compute_score(metrics, 'S1')
        second = session_score.compute_score(copy.deepcopy(metrics), 'S1')
        self.assertEqual(first, second)
        self.assertEqual(first['score_status'], 'scored')
        self.assertEqual(first['level'], 'S1')
        self.assertGreater(first['score'], 0)

    def test_s2_requires_reliable_input_ratio_instead_of_reweighting_unknown(self):
        metrics = session_score.default_metrics()
        metrics.update(round_count=20, compression_observed=True, compression_count=0)
        result = session_score.compute_score(metrics, 'S2')
        self.assertEqual(result['score_status'], 'insufficient_data')
        self.assertIsNone(result['score'])
        self.assertIn('input_ratio', result['unknown'])

        metrics.update(input_ratio=0.8, input_observed=True)
        scored = session_score.compute_score(metrics, 'S2')
        self.assertEqual(scored['score_status'], 'scored')
        self.assertEqual(scored['level'], 'S2')

    def test_missing_round_count_never_becomes_zero_score(self):
        metrics = session_score.default_metrics()
        result = session_score.compute_score(metrics, 'S1')
        self.assertEqual(result['score_status'], 'insufficient_data')
        self.assertIsNone(result['score'])

    def test_subagent_post_model_request_is_ignored(self):
        payload = {
            'cwd': str(self.root), 'session_id': 'test-thread', 'turn_id': 'turn-1',
            'hook_event_name': 'UserPromptSubmit',
        }
        self.assertEqual(session_score.handle_payload(self.root, payload), {})
        payload.update({
            'hook_event_name': 'PostModelRequest',
            'agent_id': 'subagent-1',
            'token_usage': {'input_tokens': 100, 'cached_input_tokens': 0},
        })
        self.assertEqual(session_score.handle_payload(self.root, payload), {})
        state = session_score.read_score_state(self.root, 'test-thread')
        self.assertFalse(state['metrics']['input_observed'])

    def test_stop_writes_score_and_non_blocking_message(self):
        rpc = FakeRPC(self.root)
        TitleManager(self.root, rpc, caller_thread_id='test-thread').set(
            'test-thread', '原始需求', '讨论中', self.root, progress='开始工作')
        with patch.object(session_score, 'CodexRPC', return_value=session_score.nullcontext(rpc)):
            base = {'cwd': str(self.root), 'session_id': 'test-thread', 'turn_id': 'turn-1'}
            session_score.handle_payload(self.root, {**base, 'hook_event_name': 'UserPromptSubmit'})
            session_score.handle_payload(self.root, {**base, 'hook_event_name': 'PostModelRequest',
                'status': 'completed', 'token_usage': {'input_tokens': 800,
                'cached_input_tokens': 0}, 'model_context_window': 1000})
            stop = session_score.handle_payload(self.root, {**base, 'hook_event_name': 'Stop'})
        self.assertIn('systemMessage', stop)
        self.assertNotIn('decision', stop)
        self.assertIn('S2·', rpc.thread['name'])

    def test_failures_are_fail_open(self):
        payload = {'cwd': str(self.root), 'session_id': 'test-thread',
                   'turn_id': 'turn-1', 'hook_event_name': 'PostModelRequest',
                   'token_usage': object()}
        self.assertEqual(session_score.safe_handle(self.root, payload), {})

    def test_short_large_context_is_higher_than_many_tiny_rounds(self):
        common = dict(compression_observed=True, compression_count=0,
                      input_observed=True, failure_observed=True)
        large = session_score.compute_score(dict(common, round_count=7, input_ratio=0.9), 'S2')
        tiny = session_score.compute_score(dict(common, round_count=35, input_ratio=0.1), 'S2')
        self.assertGreater(large['score'], tiny['score'])

    def test_prompt_replay_after_another_turn_does_not_double_count(self):
        metrics = None
        for turn in ('turn-a', 'turn-b', 'turn-a'):
            metrics = session_score._update_metrics(metrics, {
                'hook_event_name':'UserPromptSubmit','turn_id':turn})
        self.assertEqual(metrics['round_count'], 2)

    def test_compaction_invalidates_the_pre_compaction_input_sample(self):
        metrics = dict(session_score.default_metrics(), round_count=2,
                       compression_observed=True, input_ratio=0.9, input_observed=True)
        metrics = session_score._update_metrics(metrics, {
            'hook_event_name':'PostCompact','turn_id':'turn-c'})
        result = session_score.compute_score(metrics, 'S2')
        self.assertEqual(result['score_status'], 'insufficient_data')

    def test_cancelled_request_is_not_a_quality_failure(self):
        metrics = session_score._update_metrics(None, {
            'hook_event_name':'PostModelRequest','turn_id':'turn-a','status':'cancelled'})
        self.assertEqual(metrics['model_failure_events'], 0)

    def test_all_subagent_events_are_excluded(self):
        for event in ('UserPromptSubmit','PostCompact','PostToolUse','Stop'):
            payload = {'cwd':str(self.root),'session_id':'test-thread',
                       'turn_id':'turn-a','hook_event_name':event,'agent_id':'child',
                       'status':'failed'}
            self.assertEqual(session_score.safe_handle(self.root, payload), {})
        self.assertFalse((self.root/'.local/title-scores/test-thread.json').exists())

    def test_stop_score_handler_is_packaged(self):
        hooks = json.loads((session_score.PLUGIN_ROOT/'hooks/hooks.json').read_text())['hooks']
        commands = [h['command'] for group in hooks['Stop'] for h in group['hooks']]
        self.assertTrue(any('session_score.py' in cmd for cmd in commands))

    def test_disabled_installation_collects_nothing(self):
        p = self.root/'.local/title-installation.json'
        value = json.loads(p.read_text()); value['enabled'] = False
        p.write_text(json.dumps(value))
        result = session_score.safe_handle(self.root, {
            'cwd':str(self.root),'session_id':'test-thread','turn_id':'turn-a',
            'hook_event_name':'UserPromptSubmit'})
        self.assertEqual(result, {})
        self.assertFalse((self.root/'.local/title-scores/test-thread.json').exists())

    def test_stale_turn_stop_cannot_publish_current_turn_score(self):
        payload = {'cwd':str(self.root),'session_id':'test-thread','turn_id':'turn-new',
                   'hook_event_name':'UserPromptSubmit'}
        session_score.handle_payload(self.root,payload)
        with patch.object(session_score,'CodexRPC') as client:
            result=session_score.handle_payload(self.root,{
                **payload,'turn_id':'turn-old','hook_event_name':'Stop'})
        self.assertEqual(result,{})
        client.assert_not_called()

    def test_missing_or_malformed_window_is_unknown_not_a_zero_ratio(self):
        for usage,window in (({'input_tokens':800},None),
                             ({'input_tokens':800},-1),
                             ({'input_tokens':True},1000),
                             ({'input_tokens':1100},1000)):
            metrics=session_score._update_metrics(None,{
                'hook_event_name':'PostModelRequest','turn_id':'turn-a',
                'status':'completed','token_usage':usage,
                'model_context_window':window})
            result=session_score.compute_score(metrics,'S2')
            self.assertEqual(result['score_status'],'insufficient_data')

    def test_duplicate_compaction_post_does_not_inflate_count(self):
        metrics=None
        for event in ('UserPromptSubmit','PreCompact','PostCompact','PostCompact'):
            metrics=session_score._update_metrics(metrics,{
                'hook_event_name':event,'turn_id':'turn-a'})
        self.assertEqual(metrics['compression_count'],1)

    def test_settings_are_shared_state_and_do_not_edit_the_bundle(self):
        original=session_score.CONFIG_PATH.read_bytes()
        session_score.configure(self.root, level='S1', enabled=False)
        settings=session_score.load_config(self.root)
        self.assertEqual(settings['default_level'],'S1')
        self.assertFalse(settings['enabled'])
        self.assertEqual(session_score.CONFIG_PATH.read_bytes(),original)

    def test_config_rejects_unimplemented_levels_and_invalid_windows(self):
        for kwargs in ({'context_windows':{'model':0}},
                       {'context_windows':{'model':True}}):
            with self.assertRaises(ValueError):
                session_score.configure(self.root,**kwargs)

    def test_s3_s4_are_configurable_but_default_remains_s2(self):
        config = session_score.load_config(self.root)
        self.assertEqual(config['default_level'], 'S2')
        self.assertIn('S3', config['levels'])
        self.assertIn('S4', config['levels'])
        session_score.configure(self.root, level='S3')
        self.assertEqual(session_score.load_config(self.root)['default_level'], 'S3')

    def test_semantic_prompt_respects_configured_bound_without_dropping_command(self):
        config = session_score.load_config(self.root)
        config['semantic'] = {**config['semantic'], 'max_prompt_chars': 1500}
        thread = 'test-thread'
        turn = 'turn-3'
        prompt = session_score._semantic_instruction(
            self.root, thread, turn, 'a' * 32, 'S4',
            {'score_status': 'scored', 'score': 20, 'round_count': 3},
            [{'turn_id': 'turn-2', 'user': '用户内容' * 900,
              'assistant': '助手内容' * 900}], config)
        self.assertLessEqual(len(prompt), 1500)
        self.assertIn('semantic-submit', prompt)
        self.assertIn('--nonce ' + 'a' * 32, prompt)

    def test_probe_schedule_uses_periodic_and_threshold_edge(self):
        config = session_score.load_config(self.root)
        self.assertTrue(session_score.probe_due(3, 'S3', 10, False, config))
        self.assertTrue(session_score.probe_due(5, 'S4', 10, False, config))
        self.assertTrue(session_score.probe_due(4, 'S3', 60, False, config))
        self.assertFalse(session_score.probe_due(4, 'S3', 60, True, config))
        self.assertFalse(session_score.probe_due(2, 'S3', 59, False, config))

    def test_semantic_delta_is_program_computed_and_capped(self):
        base = {'level': 'S2', 'score_status': 'scored', 'score': 95}
        submission = {
            'schema_version': 1, 'level': 'S3',
            'labels': {
                'continuity_risk': 'high',
                'repetition_risk': 'high',
                'constraint_risk': 'high',
            },
            'evidence_strength': 'high', 'uncertainty': 'low',
            'evidence_codes': ['repeated_failure', 'missing_constraint'],
        }
        result = session_score.compute_semantic_result(base, submission, 'S3',
                                                        session_score.load_config(self.root))
        self.assertEqual(result['score'], 100)
        self.assertLessEqual(result['semantic_delta'], 10)
        self.assertNotIn('model_score', result)

    def test_unknown_semantic_label_makes_probe_unscored(self):
        base = {'level': 'S2', 'score_status': 'scored', 'score': 40}
        submission = {
            'schema_version': 1, 'level': 'S3',
            'labels': {
                'continuity_risk': 'unknown',
                'repetition_risk': 'low',
                'constraint_risk': 'low',
            },
            'evidence_strength': 'medium', 'uncertainty': 'low',
            'evidence_codes': [],
        }
        result = session_score.compute_semantic_result(base, submission, 'S3',
                                                        session_score.load_config(self.root))
        self.assertEqual(result['score_status'], 'insufficient_data')
        self.assertIsNone(result['score'])

    def test_s4_history_is_bounded_and_account_local(self):
        session_score.configure(self.root, level='S4')
        config = session_score.load_config(self.root)
        for index in range(5):
            session_score._history_prepare(self.root, 'test-thread', f'turn-{index}',
                                           '用户请求 ' + ('x' * 2000), config)
            session_score._history_finish(self.root, 'test-thread', f'turn-{index}',
                                          '助手回复 ' + ('y' * 2000), config)
        path = session_score._history_path(self.root, 'test-thread')
        value = json.loads(path.read_text())
        self.assertLessEqual(len(value['turns']), 3)
        self.assertTrue(all(len(item['user']) <= 901 and len(item['assistant']) <= 901
                             for item in value['turns']))
        other_home = Path(self.temp.name) / 'other-codex-home'
        with patch.object(session_score, 'is_global', return_value=True), \
             patch.dict(os.environ, {'CODEX_HOME': str(other_home)}):
            other_path = session_score._history_path(self.root, 'test-thread')
        self.assertNotEqual(path, other_path)

    def test_s4_tool_status_is_whitelisted_and_history_file_is_bounded(self):
        session_score.configure(self.root, level='S4')
        config = session_score.load_config(self.root)
        session_score._history_prepare(self.root, 'test-thread', 'turn-1', '请求', config)
        session_score._history_tool(self.root, 'test-thread', 'turn-1', {
            'tool_use_id': 'tool-1', 'status': 'x' * 1_000_000,
            'tool_response': {'exit_code': 0, 'isError': False}}, config)
        value = session_score._read_history(self.root, 'test-thread')
        self.assertEqual(value['active']['tools'][0]['status'], 'unknown')
        self.assertLess((session_score._history_path(self.root, 'test-thread')).stat().st_size,
                         session_score.MAX_HISTORY_FILE_BYTES)

    def test_history_clear_waits_for_active_history_writer(self):
        session_score.configure(self.root, level='S4')
        config = session_score.load_config(self.root)
        session_score._history_prepare(self.root, 'test-thread', 'turn-1', '请求', config)
        lock_path = session_score._history_lock_path(self.root, 'test-thread')
        entered = threading.Event()
        release = threading.Event()

        def hold_history_lock():
            with session_score.locked(lock_path):
                entered.set()
                release.wait(5)

        holder = threading.Thread(target=hold_history_lock, daemon=True)
        holder.start()
        self.assertTrue(entered.wait(2))
        clearer = threading.Thread(
            target=session_score._invalidate_runtime_state,
            args=(self.root,), kwargs={'clear_history': True}, daemon=True)
        clearer.start()
        deadline = time.monotonic() + 2
        while not clearer.is_alive() and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertTrue(clearer.is_alive())
        release.set()
        holder.join(2)
        clearer.join(2)
        self.assertFalse(clearer.is_alive())
        self.assertFalse(session_score._history_path(self.root, 'test-thread').exists())

    def test_history_writer_rechecks_configuration_after_waiting(self):
        session_score.configure(self.root, level='S4')
        stale = session_score.load_config(self.root)
        session_score.configure(self.root, level='S2')
        session_score._history_prepare(self.root, 'test-thread', 'turn-1', '请求', stale)
        self.assertFalse(session_score._history_path(self.root, 'test-thread').exists())

    def test_score_state_path_rejects_invalid_session_id(self):
        with self.assertRaises(session_score.TitleError):
            session_score.score_state_path(self.root, '../outside')

    def test_post_tool_use_does_not_write_history_with_stale_config(self):
        session_score.configure(self.root, level='S4')
        prompt = {
            'cwd': str(self.root), 'session_id': 'test-thread', 'turn_id': 'turn-1',
            'hook_event_name': 'UserPromptSubmit', 'prompt': '请求',
        }
        session_score.handle_payload(self.root, prompt)
        original_load_config = session_score.load_config
        calls = 0

        def load_config_with_late_downgrade(root):
            nonlocal calls
            calls += 1
            value = original_load_config(root)
            if calls >= 3:
                value = {**value, 'default_level': 'S2'}
            return value

        with patch.object(session_score, 'load_config', side_effect=load_config_with_late_downgrade):
            session_score.handle_payload(self.root, {
                'cwd': str(self.root), 'session_id': 'test-thread', 'turn_id': 'turn-1',
                'hook_event_name': 'PostToolUse', 'tool_use_id': 'tool-1',
                'status': 'failed', 'tool_response': {'isError': True},
            })
        history = session_score._read_history(self.root, 'test-thread')
        self.assertEqual(history['active']['tools'], [])

    def test_title_snapshot_rejects_local_symlink_and_oversize_state(self):
        external = Path(self.temp.name) / 'external-local'
        (external / 'titles').mkdir(parents=True)
        external_title = external / 'titles' / 'test-thread.json'
        external_title.write_text(json.dumps({'last_applied': '讨论中｜外部｜不应读取'}))
        local = self.root / '.local'
        moved = Path(self.temp.name) / 'original-local'
        local.rename(moved)
        try:
            local.symlink_to(external, target_is_directory=True)
            self.assertIsNone(session_score._title_snapshot(self.root, 'test-thread'))
        finally:
            local.unlink()
            moved.rename(local)

        titles = local / 'titles'
        titles.mkdir(exist_ok=True)
        (titles / 'test-thread.json').write_text(json.dumps({
            'last_applied': '讨论中｜需求｜进展',
            'padding': 'x' * 100_000,
        }))
        self.assertIsNone(session_score._title_snapshot(self.root, 'test-thread'))

    def test_invalid_submission_consumes_the_only_attempt(self):
        session_score.configure(self.root, level='S3', window_mode='reference')
        state = session_score.read_score_state(self.root, 'test-thread')
        state['metrics'] = session_score.default_metrics()
        state['metrics'].update(round_count=2, last_turn_id='turn-2',
                                compression_observed=True, input_ratio=.1,
                                input_observed=True, failure_observed=True)
        state['score_result'] = {'level': 'S2', 'score_status': 'scored', 'score': 10}
        session_score.save_score_state(self.root, 'test-thread', state)
        prompt = session_score.prepare_prompt(self.root, {
            'cwd': str(self.root), 'session_id': 'test-thread', 'turn_id': 'turn-3',
            'hook_event_name': 'UserPromptSubmit', 'prompt': '继续'})
        nonce = re.search(r'--nonce ([^ ]+)', prompt['hookSpecificOutput']['additionalContext']).group(1)
        invalid = {'schema_version': 1, 'level': 'S3', 'labels': {},
                   'evidence_strength': 'low', 'uncertainty': 'low', 'evidence_codes': []}
        with patch.dict(os.environ, {'CODEX_THREAD_ID': 'test-thread'}):
            self.assertEqual(session_score.accept_semantic_submission(
                self.root, 'test-thread', 'turn-3', nonce, invalid)['result'], 'rejected')
            self.assertEqual(session_score.accept_semantic_submission(
                self.root, 'test-thread', 'turn-3', nonce, invalid)['result'], 'rejected')
        pending = session_score.read_score_state(self.root, 'test-thread')['pending_probe']
        self.assertTrue(pending['attempt_used'])
        self.assertEqual(pending['status'], 'invalid')

    def test_same_turn_probe_accepts_one_submission_and_scores_at_stop(self):
        session_score.configure(self.root, level='S3', window_mode='reference')
        rpc = FakeRPC(self.root)
        TitleManager(self.root, rpc, caller_thread_id='test-thread').set(
            'test-thread', '原始需求', '讨论中', self.root, progress='开始工作')
        state = session_score.read_score_state(self.root, 'test-thread')
        state['metrics'] = session_score.default_metrics()
        state['metrics'].update(round_count=2, last_turn_id='turn-2',
                                compression_observed=True, compression_count=0,
                                input_ratio=.1, input_observed=True,
                                failure_observed=True)
        state['score_result'] = {'level': 'S2', 'score_status': 'scored', 'score': 10}
        session_score.save_score_state(self.root, 'test-thread', state)
        prompt = session_score.prepare_prompt(self.root, {
            'cwd': str(self.root), 'session_id': 'test-thread', 'turn_id': 'turn-3',
            'hook_event_name': 'UserPromptSubmit', 'prompt': '继续修复测试'})
        self.assertIn('hookSpecificOutput', prompt)
        pending = session_score.read_score_state(self.root, 'test-thread')['pending_probe']
        self.assertEqual(pending['level'], 'S3')
        nonce = re.search(r'--nonce ([^ ]+)', prompt['hookSpecificOutput']['additionalContext']).group(1)
        submission = {
            'schema_version': 1, 'level': 'S3',
            'labels': {'continuity_risk': 'low', 'repetition_risk': 'medium',
                       'constraint_risk': 'none'},
            'evidence_strength': 'medium', 'uncertainty': 'low',
            'evidence_codes': ['repeated_failure'],
        }
        with patch.dict(os.environ, {'CODEX_THREAD_ID': 'test-thread'}):
            accepted = session_score.accept_semantic_submission(
                self.root, 'test-thread', 'turn-3', nonce, submission)
        self.assertEqual(accepted['result'], 'accepted')
        with patch.dict(os.environ, {'CODEX_THREAD_ID': 'test-thread'}):
            self.assertEqual(session_score.accept_semantic_submission(
                self.root, 'test-thread', 'turn-3', nonce, submission)['result'],
                             'rejected')
        with patch.object(session_score, 'CodexRPC', return_value=session_score.nullcontext(rpc)):
            session_score.handle_payload(self.root, {
                'cwd': str(self.root), 'session_id': 'test-thread', 'turn_id': 'turn-3',
                'hook_event_name': 'PostModelRequest', 'status': 'completed',
                'token_usage': {'input_tokens': 100}, 'model_context_window': 1000})
            result = session_score.handle_payload(self.root, {
                'cwd': str(self.root), 'session_id': 'test-thread', 'turn_id': 'turn-3',
                'hook_event_name': 'Stop',
                'last_assistant_message': '已完成测试'})
        self.assertNotIn('未评分', result.get('systemMessage', ''))
        self.assertTrue(rpc.thread['name'].startswith('S3·'))
        duplicate = session_score.handle_payload(self.root, {
            'cwd': str(self.root), 'session_id': 'test-thread', 'turn_id': 'turn-3',
            'hook_event_name': 'Stop', 'last_assistant_message': '重复结束事件'})
        self.assertTrue(rpc.thread['name'].startswith('S3·'))
        self.assertEqual(session_score.read_score_state(self.root, 'test-thread')
                         ['score_result']['level'], 'S3')
        self.assertEqual(duplicate, {})

    def test_probe_is_once_per_turn_even_when_prompt_is_replayed_after_stop(self):
        session_score.configure(self.root, level='S3', window_mode='reference')
        state = session_score.read_score_state(self.root, 'test-thread')
        state['metrics'] = session_score.default_metrics()
        state['metrics'].update(round_count=2, last_turn_id='turn-2',
                                compression_observed=True, input_ratio=.1,
                                input_observed=True, failure_observed=True)
        state['score_result'] = {'level': 'S2', 'score_status': 'scored', 'score': 10}
        session_score.save_score_state(self.root, 'test-thread', state)
        payload = {'cwd': str(self.root), 'session_id': 'test-thread', 'turn_id': 'turn-3',
                   'hook_event_name': 'UserPromptSubmit', 'prompt': '继续'}
        prepared = session_score.prepare_prompt(self.root, payload)
        self.assertIn('hookSpecificOutput', prepared)
        with patch.object(session_score, 'CodexRPC', return_value=session_score.nullcontext(FakeRPC(self.root))):
            session_score.handle_payload(self.root, {**payload, 'hook_event_name': 'Stop',
                                                      'last_assistant_message': '完成'})
        self.assertEqual(session_score.prepare_prompt(self.root, payload), {})
        self.assertNotIn('pending_probe', session_score.read_score_state(self.root, 'test-thread'))

    def test_config_change_expires_old_probe_without_publishing_old_level(self):
        session_score.configure(self.root, level='S3', window_mode='reference')
        state = session_score.read_score_state(self.root, 'test-thread')
        state['metrics'] = session_score.default_metrics()
        state['metrics'].update(round_count=2, last_turn_id='turn-2',
                                compression_observed=True, input_ratio=.1,
                                input_observed=True, failure_observed=True)
        state['score_result'] = {'level': 'S2', 'score_status': 'scored', 'score': 10}
        session_score.save_score_state(self.root, 'test-thread', state)
        payload = {'cwd': str(self.root), 'session_id': 'test-thread', 'turn_id': 'turn-3',
                   'hook_event_name': 'UserPromptSubmit', 'prompt': '继续'}
        self.assertIn('hookSpecificOutput', session_score.prepare_prompt(self.root, payload))
        session_score.configure(self.root, level='S2')
        with patch.object(session_score, 'CodexRPC', return_value=session_score.nullcontext(FakeRPC(self.root))):
            session_score.handle_payload(self.root, {**payload, 'hook_event_name': 'Stop',
                                                      'last_assistant_message': '完成'})
        result = session_score.read_score_state(self.root, 'test-thread')['score_result']
        self.assertEqual(result['level'], 'S2')
        self.assertNotIn('pending_probe', session_score.read_score_state(self.root, 'test-thread'))

    def test_config_change_makes_finalized_result_non_reusable_on_duplicate_stop(self):
        session_score.configure(self.root, level='S3', window_mode='reference')
        state = session_score.read_score_state(self.root, 'test-thread')
        state['metrics'] = session_score.default_metrics()
        state['metrics'].update(round_count=2, last_turn_id='turn-2',
                                compression_observed=True, input_ratio=.1,
                                input_observed=True, failure_observed=True)
        state['score_result'] = {'level': 'S2', 'score_status': 'scored', 'score': 10}
        session_score.save_score_state(self.root, 'test-thread', state)
        payload = {'cwd': str(self.root), 'session_id': 'test-thread', 'turn_id': 'turn-3',
                   'hook_event_name': 'UserPromptSubmit', 'prompt': '继续'}
        self.assertIn('hookSpecificOutput', session_score.prepare_prompt(self.root, payload))
        rpc = FakeRPC(self.root)
        with patch.object(session_score, 'CodexRPC', return_value=session_score.nullcontext(rpc)):
            session_score.handle_payload(self.root, {**payload, 'hook_event_name': 'Stop',
                                                      'last_assistant_message': '完成'})
        session_score.configure(self.root, level='S2')
        with patch.object(session_score, 'CodexRPC', return_value=session_score.nullcontext(rpc)):
            session_score.handle_payload(self.root, {**payload, 'hook_event_name': 'Stop',
                                                      'last_assistant_message': '重复结束'})
        result = session_score.read_score_state(self.root, 'test-thread')['score_result']
        self.assertEqual(result['level'], 'S2')

    def test_submission_requires_current_caller_thread_environment(self):
        session_score.configure(self.root, level='S3', window_mode='reference')
        state = session_score.read_score_state(self.root, 'test-thread')
        state['metrics'] = session_score.default_metrics()
        state['metrics'].update(round_count=2, last_turn_id='turn-2',
                                compression_observed=True, input_ratio=.1,
                                input_observed=True, failure_observed=True)
        state['score_result'] = {'level': 'S2', 'score_status': 'scored', 'score': 10}
        session_score.save_score_state(self.root, 'test-thread', state)
        prompt = session_score.prepare_prompt(self.root, {
            'cwd': str(self.root), 'session_id': 'test-thread', 'turn_id': 'turn-3',
            'hook_event_name': 'UserPromptSubmit', 'prompt': '继续'})
        nonce = re.search(r'--nonce ([^ ]+)', prompt['hookSpecificOutput']['additionalContext']).group(1)
        submission = {'schema_version': 1, 'level': 'S3',
                      'labels': {'continuity_risk': 'low', 'repetition_risk': 'low',
                                 'constraint_risk': 'low'},
                      'evidence_strength': 'low', 'uncertainty': 'low', 'evidence_codes': []}
        with patch.dict(os.environ, {'CODEX_THREAD_ID': ''}):
            result = session_score.accept_semantic_submission(
                self.root, 'test-thread', 'turn-3', nonce, submission)
        self.assertEqual(result, {'result': 'rejected', 'reason': 'caller'})

    def test_wrong_nonce_or_malformed_submission_consumes_probe_attempt(self):
        session_score.configure(self.root, level='S3', window_mode='reference')
        state = session_score.read_score_state(self.root, 'test-thread')
        state['metrics'] = session_score.default_metrics()
        state['metrics'].update(round_count=2, last_turn_id='turn-2',
                                compression_observed=True, input_ratio=.1,
                                input_observed=True, failure_observed=True)
        state['score_result'] = {'level': 'S2', 'score_status': 'scored', 'score': 10}
        session_score.save_score_state(self.root, 'test-thread', state)
        prompt = session_score.prepare_prompt(self.root, {
            'cwd': str(self.root), 'session_id': 'test-thread', 'turn_id': 'turn-3',
            'hook_event_name': 'UserPromptSubmit', 'prompt': '继续'})
        nonce = re.search(r'--nonce ([^ ]+)', prompt['hookSpecificOutput']['additionalContext']).group(1)
        with patch.dict(os.environ, {'CODEX_THREAD_ID': 'test-thread'}):
            result = session_score._consume_probe_attempt(
                self.root, 'test-thread', 'turn-3', nonce + 'wrong', 'json')
        self.assertEqual(result, {'result': 'rejected', 'reason': 'json'})
        pending = session_score.read_score_state(self.root, 'test-thread')['pending_probe']
        self.assertTrue(pending['attempt_used'])
        self.assertEqual(pending['status'], 'invalid')
        with patch.dict(os.environ, {'CODEX_THREAD_ID': 'test-thread'}):
            self.assertEqual(session_score.accept_semantic_submission(
                self.root, 'test-thread', 'turn-3', nonce, {})['reason'], 'stale')

    def test_invalid_probe_is_unscored_without_s2_fallback(self):
        session_score.configure(self.root, level='S3', window_mode='reference')
        rpc = FakeRPC(self.root)
        TitleManager(self.root, rpc, caller_thread_id='test-thread').set(
            'test-thread', '原始需求', '讨论中', self.root, progress='开始工作')
        state = session_score.read_score_state(self.root, 'test-thread')
        state['metrics'] = session_score.default_metrics()
        state['metrics'].update(round_count=2, last_turn_id='turn-2',
                                compression_observed=True, input_ratio=.1,
                                input_observed=True, failure_observed=True)
        state['score_result'] = {'level': 'S2', 'score_status': 'scored', 'score': 70}
        session_score.save_score_state(self.root, 'test-thread', state)
        session_score.prepare_prompt(self.root, {
            'cwd': str(self.root), 'session_id': 'test-thread', 'turn_id': 'turn-3',
            'hook_event_name': 'UserPromptSubmit', 'prompt': '继续'})
        with patch.object(session_score, 'CodexRPC', return_value=session_score.nullcontext(rpc)):
            result = session_score.handle_payload(self.root, {
                'cwd': str(self.root), 'session_id': 'test-thread', 'turn_id': 'turn-3',
                'hook_event_name': 'Stop', 'last_assistant_message': '未提交评估'})
        self.assertIn('未评分', result.get('systemMessage', ''))
        self.assertTrue(rpc.thread['name'].startswith('未评分｜'))

    def test_reference_window_is_opt_in_exact_model_and_provenance_is_retained(self):
        home=Path(os.environ['CODEX_HOME']);home.mkdir(parents=True,exist_ok=True)
        (home/'models_cache.json').write_text(json.dumps({
            'client_version':'test-cli','fetched_at':'2026-11-07T00:00:00Z',
            'models':[{'slug':'example','context_window':1000,
                       'effective_context_window_percent':95}]}))
        self.assertIsNone(session_score.resolve_window({'model':'example'},
            {'window_mode':'actual_only','context_windows':{}})[0])
        window,meta=session_score.resolve_window({'model':'example'},
            {'window_mode':'reference','context_windows':{}})
        self.assertEqual(window,950)
        self.assertEqual(meta['source'],'reference_cache')
        self.assertIsNone(session_score.resolve_window({'model':'other'},
            {'window_mode':'reference','context_windows':{}})[0])

    def test_explicit_window_overrides_cache_and_is_labeled(self):
        window,meta=session_score.resolve_window({'model':'example'},
            {'window_mode':'reference','context_windows':{'example':2000}})
        self.assertEqual(window,2000)
        self.assertEqual(meta['source'],'user_configured')

    def test_scoring_acceptance_examples_and_bounds(self):
        common=dict(compression_observed=True,compression_count=0,
                    failure_observed=True,input_observed=True)
        for n,p,expected in ((7,0.9,73),(35,0.1,13)):
            result=session_score.compute_score(dict(common,round_count=n,input_ratio=p),'S2')
            self.assertEqual(result['score'],expected)
        self.assertEqual(session_score.compute_score(dict(common,round_count=20,
            compression_count=1),'S1')['score'],46)
        for p in (0,.1,.3,.5,.8,.9,1):
            previous=-1
            for n in (0,1,7,20,40,100,10000):
                result=session_score.compute_score(dict(common,round_count=n,input_ratio=p),'S2')
                self.assertGreaterEqual(result['score'],previous)
                self.assertLessEqual(result['score'],100)
                self.assertGreaterEqual(result['score'],0)
                previous=result['score']
        previous=-1
        for p in (0,.1,.3,.5,.8,.9,1):
            score=session_score.compute_score(dict(common,round_count=7,input_ratio=p),'S2')['score']
            self.assertGreaterEqual(score,previous)
            previous=score

    def test_repeated_root_failures_are_bounded_and_deduplicated_per_turn(self):
        metrics=None
        for turn in ('turn-1','turn-2','turn-3'):
            metrics=session_score._update_metrics(metrics,{'hook_event_name':'UserPromptSubmit',
                'turn_id':turn})
            for _ in range(3):
                metrics=session_score._update_metrics(metrics,{'hook_event_name':'PostModelRequest',
                    'turn_id':turn,'status':'failed'})
        self.assertEqual(len(metrics['failed_turn_ids']),3)

    def test_compaction_summary_is_excluded_until_a_fresh_request(self):
        metrics=None
        for payload in (
            {'hook_event_name':'UserPromptSubmit','turn_id':'turn-1'},
            {'hook_event_name':'PreCompact','turn_id':'turn-1'},
            {'hook_event_name':'PostModelRequest','turn_id':'turn-1','status':'completed',
             'token_usage':{'input_tokens':900},'model_context_window':1000},
            {'hook_event_name':'PostCompact','turn_id':'turn-1'},
        ):
            metrics=session_score._update_metrics(metrics,payload)
            if payload['hook_event_name']!='UserPromptSubmit':
                self.assertIsNone(metrics['input_ratio'])
        metrics=session_score._update_metrics(metrics,{'hook_event_name':'PostModelRequest',
            'turn_id':'turn-1','status':'completed','token_usage':{'input_tokens':100},
            'model_context_window':1000})
        self.assertEqual(metrics['input_ratio'],.1)

    def test_expired_failures_do_not_reappear_from_lifetime_counters(self):
        metrics=None
        for i in range(25):
            turn=f'turn-{i}'
            metrics=session_score._update_metrics(metrics,{'hook_event_name':'UserPromptSubmit','turn_id':turn})
            if i<3:
                metrics=session_score._update_metrics(metrics,{'hook_event_name':'PostModelRequest','turn_id':turn,'status':'failed'})
        metrics.update(input_ratio=.1,failure_observed=True)
        score=session_score.compute_score(metrics,'S2')
        self.assertEqual(score['contributions']['failure'],0)

    def test_new_turn_recovers_from_missing_post_compact_event(self):
        metrics=None
        for event,turn in [('UserPromptSubmit','a'),('PreCompact','a'),('UserPromptSubmit','b')]:
            metrics=session_score._update_metrics(metrics,{'hook_event_name':event,'turn_id':turn})
        metrics=session_score._update_metrics(metrics,{'hook_event_name':'PostModelRequest','turn_id':'b',
            'status':'completed','token_usage':{'input_tokens':100},'model_context_window':1000})
        self.assertEqual(metrics['input_ratio'],.1)

    def test_disabled_hook_clears_prefix_after_a_new_prompt(self):
        rpc=FakeRPC(self.root)
        manager=TitleManager(self.root,rpc,caller_thread_id='test-thread')
        manager.set('test-thread','需求','实现中',self.root,progress='测试')
        manager.set_score('test-thread','S2','scored',70,self.root)
        base={'cwd':str(self.root),'session_id':'test-thread','turn_id':'turn-a'}
        session_score.handle_payload(self.root,{**base,'hook_event_name':'UserPromptSubmit'})
        session_score.configure(self.root,enabled=False)
        with patch.object(session_score,'CodexRPC',return_value=session_score.nullcontext(rpc)):
            session_score.handle_payload(self.root,{**base,'turn_id':'turn-b','hook_event_name':'UserPromptSubmit'})
            result=session_score.handle_payload(self.root,{**base,'turn_id':'turn-b','hook_event_name':'Stop'})
        self.assertEqual(result,{})
        self.assertEqual(rpc.thread['name'],'实现中｜需求｜测试')

    def test_prefix_transport_failure_does_not_lose_a_valid_notice(self):
        base={'cwd':str(self.root),'session_id':'test-thread','turn_id':'turn-a'}
        session_score.handle_payload(self.root,{**base,'hook_event_name':'UserPromptSubmit'})
        with patch.object(session_score,'CodexRPC',side_effect=OSError('test transport unavailable')):
            result=session_score.handle_payload(self.root,{**base,'hook_event_name':'Stop'})
        self.assertIn('systemMessage',result)
        self.assertNotIn('decision',result)

    def test_recent_failures_stay_in_the_twenty_turn_window(self):
        metrics=None
        for i in range(25):
            turn=f'turn-{i}'
            metrics=session_score._update_metrics(metrics,{'hook_event_name':'UserPromptSubmit','turn_id':turn})
            if i in {0,1,2,21,24}:
                metrics=session_score._update_metrics(metrics,{'hook_event_name':'PostModelRequest','turn_id':turn,'status':'failed'})
        metrics.update(input_ratio=.1,failure_observed=True)
        score=session_score.compute_score(metrics,'S2')
        self.assertEqual(score['contributions']['failure'],3.33)

    def test_notice_survives_actual_rpc_and_title_error_types(self):
        from clarity_rpc import RPCError
        from title_runtime import TitleError
        base={'cwd':str(self.root),'session_id':'test-thread','turn_id':'turn-a'}
        session_score.handle_payload(self.root,{**base,'hook_event_name':'UserPromptSubmit'})
        for error in (TitleError('unmatched readback'),RPCError('transport uncertain')):
            state=session_score.read_score_state(self.root,'test-thread')
            state.pop('score_fingerprint',None)
            session_score.save_score_state(self.root,'test-thread',state)
            with patch.object(session_score,'CodexRPC',return_value=session_score.nullcontext(FakeRPC(self.root))),\
                 patch.object(session_score.TitleManager,'set_score',side_effect=error) as setter:
                result=session_score.handle_payload(self.root,{**base,'hook_event_name':'Stop'})
                setter.assert_called_once()
            self.assertIn('systemMessage',result)
            self.assertNotIn('decision',result)


if __name__ == '__main__':
    unittest.main()
