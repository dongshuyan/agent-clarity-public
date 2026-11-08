#!/usr/bin/env python3
"""Reproduce the desktop's short-answer path; archive only the generated test chat."""
import argparse
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from codex_rpc import CodexRPC
from codex_session import start_session, run_turn
from title_plugin import Installer


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true', required=True)
    parser.add_argument('--model', default='gpt-6-luna')
    parser.add_argument('--effort', default='medium')
    parser.add_argument('--exercise-repair', action='store_true',
                        help='故障注入：要求首条回答先不调用工具，验证 Stop 的一次补做路径')
    args = parser.parse_args()
    installation = Installer(ROOT).status()
    if not installation.get('runtime_ready'):
        raise RuntimeError('标题插件的两个 Hooks 尚未就绪；请先通过官方 /hooks 审查')
    plugin_root = Path(installation['skill_path']).parents[2]
    folder = ROOT / '.local' / ('short-title-' + str(time.time_ns()))
    folder.mkdir(parents=True)
    result = {'model': args.model, 'effort': args.effort, 'passed': False,
              'scenario': 'instructed_initial_omission' if args.exercise_repair else 'reported_cache_question'}
    with CodexRPC(cwd=ROOT, timeout=30) as rpc:
        response = start_session(rpc, ROOT, model=args.model, effort=args.effort,
                                 ephemeral=False, sandbox='danger-full-access')
        thread_id = response['thread']['id']
        result['thread_id'] = thread_id
        try:
            prompt = ('[$clear-communication](' + str(ROOT / '.agents/skills/clear-communication/SKILL.md') + ')\n'
                      '请向不懂编程的同事解释什么是缓存，以及为什么修改后有时不能马上看到结果。')
            if args.exercise_repair:
                prompt = ('这是标题插件的漏做恢复测试：第一条最终回复前请暂不执行任何工具，'
                          '先直接用一句话解释什么是缓存。随后若收到结束检查要求补做标题的反馈，'
                          '再按反馈执行标题维护，完成后结束本轮。这是一次明确限定的测试。')
            with (folder / 'events.jsonl').open('w') as events:
                answer = run_turn(rpc, thread_id, prompt, events=events)
            (folder / 'answer.md').write_text(answer)
            title = rpc.request('thread/read', {'threadId': thread_id, 'includeTurns': False})['thread']['name']
            result['title'] = title
            rows = [json.loads(line) for line in (folder / 'events.jsonl').read_text().splitlines()]
            hooks = [row['params']['run'] for row in rows if row.get('method') == 'hook/completed'
                     and row['params'].get('threadId') == thread_id
                     and Path(row['params']['run']['sourcePath']).is_relative_to(plugin_root)]
            result['hooks'] = [{'event': run['eventName'], 'status': run['status']} for run in hooks]
            turn_path = ROOT / '.local/title-turns' / f'{thread_id}.json'
            state_path = ROOT / '.local/titles' / f'{thread_id}.json'
            turn = json.loads(turn_path.read_text()) if turn_path.exists() else {}
            state = json.loads(state_path.read_text()) if state_path.exists() else {}
            result['repair_requested'] = turn.get('repair_requested')
            result['final_answer_count'] = sum(row.get('method') == 'item/completed'
                and row['params'].get('item', {}).get('type') == 'agentMessage'
                and row['params']['item'].get('phase') == 'final_answer' for row in rows)
            result['nonempty_final_answer_count'] = sum(row.get('method') == 'item/completed'
                and row['params'].get('item', {}).get('type') == 'agentMessage'
                and row['params']['item'].get('phase') == 'final_answer'
                and bool(row['params']['item'].get('text')) for row in rows)
            result['checks'] = {
                'title_format': isinstance(title, str) and title.startswith('已完成｜')
                                and len(title.split('｜')) == 3 and all(title.split('｜')),
                'prompt_hook_ran': any(h['eventName'] == 'userPromptSubmit' and h['status'] == 'completed'
                                       for h in hooks),
                'stop_hook_ran': any(h['eventName'] == 'stop' and h['status'] in ('completed', 'blocked')
                                     for h in hooks),
                'current_turn_checked': bool(turn.get('turn_id'))
                                        and state.get('checked_turn_id') == turn['turn_id'],
                'stored_title_matches': state.get('last_applied') == title,
            }
            if args.exercise_repair:
                result['checks']['one_repair_only'] = turn.get('repair_requested') is True
                result['checks']['one_stop_block'] = sum(h['eventName'] == 'stop'
                    and h['status'] == 'blocked' for h in hooks) == 1
            result['passed'] = all(result['checks'].values())
        finally:
            try:
                rpc.request('thread/archive', {'threadId': thread_id})
                result['test_chat_archived'] = True
            finally:
                (folder / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps({'folder': str(folder), **result}, ensure_ascii=False, indent=2), flush=True)
    if not result['passed']:
        raise RuntimeError('简短问答没有生成三段式标题，见本地证据')


if __name__ == '__main__':
    main()
