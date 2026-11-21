import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'plugins/clarity-session-titles/scripts'))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_titles import FakeRPC  # noqa: E402
from title_runtime import TitleManager, TitleError, activate  # noqa: E402
from title_score import (  # noqa: E402
    parse_score_prefix,
    render_score_prefix,
)
from title_segments import parse_three_part_title  # noqa: E402


class TitleScoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.env = unittest.mock.patch.dict(
            os.environ, {'CODEX_HOME': str(Path(self.temp.name) / 'codex-home')})
        self.env.start()
        self.root = Path(self.temp.name).resolve() / 'project'
        self.root.mkdir()
        subprocess.run(['git', 'init', '-q', str(self.root)], check=True)
        activate(self.root, now=100)
        self.rpc = FakeRPC(self.root)
        self.manager = TitleManager(self.root, self.rpc, caller_thread_id='test-thread')

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def set_title(self, status='讨论中', progress='开始工作'):
        return self.manager.set(
            'test-thread', '原始需求', status, self.root, progress=progress)

    def set_score(self, level='S2', score_status='scored', score=68):
        return self.manager.set_score(
            'test-thread', level, score_status, score, self.root)

    def test_score_prefix_rendering_and_validation(self):
        self.assertEqual(render_score_prefix('S2', 'scored', 68), 'S2·68分')
        self.assertEqual(render_score_prefix('S2', 'insufficient_data', None), '未评分')
        self.assertIsNone(render_score_prefix(None, 'disabled', None))
        with self.assertRaises(TitleError):
            render_score_prefix('S5', 'scored', 68)
        with self.assertRaises(TitleError):
            render_score_prefix('S2', 'scored', 101)

    def test_score_prefix_is_ignored_by_three_part_parser(self):
        title = 'S2·68分｜讨论中｜原始需求｜开始工作'
        parsed = parse_three_part_title(title)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed[2], ('讨论中', '原始需求', '开始工作'))
        self.assertEqual(parse_score_prefix(title), 'S2·68分')
        worktree = '[工作树]S2·68分｜讨论中｜原始需求｜开始工作'
        self.assertEqual(parse_score_prefix(worktree), 'S2·68分')
        self.assertEqual(parse_three_part_title(worktree)[2], parsed[2])

    def test_set_score_adds_prefix_and_regular_title_updates_preserve_it(self):
        self.set_title()
        self.assertEqual(self.set_score()['title'], 'S2·68分｜讨论中｜原始需求｜开始工作')
        result = self.set_title(status='验证中', progress='检查显示')
        self.assertEqual(result['title'], 'S2·68分｜验证中｜原始需求｜检查显示')

    def test_baseline_prefix_preserves_manual_segments_and_only_represents_missing_s2(self):
        self.set_title()
        status = self.manager.set_score('test-thread', 'S2', 'insufficient_data', None,
                                        self.root, baseline_score=12)
        self.assertTrue(status['title'].startswith('S1·12分（窗口未知）｜'))
        self.assertEqual(parse_three_part_title(status['title'])[2][1], '原始需求')
        self.rpc.thread['name'] = status['title'].replace('开始工作', '手动进展')
        self.assertTrue(self.set_score()['title'].endswith('｜手动进展'))
        for level, kind, score in (('S4', 'insufficient_data', None), ('S2', 'scored', 10)):
            with self.assertRaises(TitleError):
                render_score_prefix(level, kind, score, baseline_score=12)

    def test_score_update_is_noop_when_rendered_prefix_is_unchanged(self):
        self.set_title()
        self.set_score()
        writes = len(self.rpc.writes)
        self.assertEqual(self.set_score()['result'], 'unchanged')
        self.assertEqual(len(self.rpc.writes), writes)

    def test_lost_score_write_ack_is_reconciled_without_duplicate_write(self):
        self.set_title()
        self.rpc.lose_ack = True
        with self.assertRaises(TitleError):
            self.set_score()
        writes = len(self.rpc.writes)
        self.assertEqual(self.set_score()['result'], 'unchanged')
        self.assertEqual(len(self.rpc.writes), writes)

    def test_insufficient_data_uses_unscored_prefix(self):
        self.set_title()
        self.set_score(score_status='insufficient_data', score=None)
        self.assertEqual(self.rpc.thread['name'], '未评分｜讨论中｜原始需求｜开始工作')
        self.assertEqual(self.set_title(status='已完成')['title'], '未评分｜已完成｜原始需求｜开始工作')

    def test_disabled_clears_a_machine_written_prefix(self):
        self.set_title()
        self.set_score()
        result = self.set_score(score_status='disabled', score=None)
        self.assertEqual(result['result'], 'updated')
        self.assertEqual(self.rpc.thread['name'], '讨论中｜原始需求｜开始工作')

    def test_manual_score_prefix_pauses_only_score_updates(self):
        self.set_title()
        self.set_score()
        self.rpc.thread['name'] = 'S2·77分｜讨论中｜原始需求｜开始工作'
        result = self.set_score(score=80)
        self.assertEqual(result['result'], 'paused')
        self.assertEqual(self.rpc.thread['name'], 'S2·77分｜讨论中｜原始需求｜开始工作')
        semantic = self.set_title(status='已完成', progress='保留手动分数')
        self.assertEqual(semantic['title'], 'S2·77分｜已完成｜原始需求｜保留手动分数')

    def test_score_state_is_separate_from_semantic_title_state(self):
        self.set_title()
        self.set_score()
        semantic = json.loads((self.root / '.local/titles/test-thread.json').read_text())
        score = json.loads((self.root / '.local/title-scores/test-thread.json').read_text())
        self.assertNotIn('score', semantic)
        self.assertEqual(score['last_written_prefix'], 'S2·68分')

    def test_score_write_does_not_hide_manual_semantic_edits(self):
        self.set_title()
        self.set_score()
        self.rpc.thread['name'] = 'S2·68分｜讨论中｜原始需求｜用户的进展'
        self.set_score(score=70)
        result = self.set_title(status='验证中', progress='自动新进展')
        self.assertEqual(result['title'], 'S2·70分｜验证中｜原始需求｜用户的进展')

    def test_score_does_not_write_over_pending_semantic_update(self):
        self.set_title()
        self.rpc.fail_write = True
        with self.assertRaises(TitleError):
            self.set_title(status='验证中', progress='等待确认')
        self.rpc.fail_write = False
        before = list(self.rpc.writes)
        result = self.set_score()
        self.assertEqual(result['result'], 'pending')
        self.assertEqual(self.rpc.writes, before)

    def test_queued_old_score_cannot_publish_after_next_prompt(self):
        self.set_title()
        from title_runtime import default_score_state, save_score_state
        state=default_score_state();state['metrics']={'last_turn_id':'new-turn'}
        save_score_state(self.root,'test-thread',state)
        result=self.manager.set_score('test-thread','S2','scored',90,self.root,
                                      expected_turn_id='old-turn')
        self.assertEqual(result['result'],'outdated')
        self.assertNotIn('S2',self.rpc.thread['name'])

    def test_definitively_rejected_score_can_retry_but_timeout_stays_pending(self):
        from clarity_rpc import RPCError
        self.set_title()
        original=self.rpc.request
        def reject(method,params):
            if method=='thread/name/set':raise RPCError('rejected',{'code':-32602,'message':'invalid params'})
            return original(method,params)
        with patch.object(self.rpc,'request',side_effect=reject):
            with self.assertRaises(RPCError):self.set_score()
        self.assertEqual(self.set_score()['result'],'updated')

        def timeout(method,params):
            if method=='thread/name/set':raise RPCError('timeout')
            return original(method,params)
        with patch.object(self.rpc,'request',side_effect=timeout):
            with self.assertRaises(RPCError):self.set_score(score=90)
        self.assertEqual(self.set_score(score=90)['result'],'pending')


if __name__ == '__main__':
    unittest.main()
