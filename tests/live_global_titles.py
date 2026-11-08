#!/usr/bin/env python3
"""Opt-in real global title test across a non-Git folder and a separate Git root."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from codex_rpc import CodexRPC
from codex_session import start_session, run_turn
from title_plugin import Installer


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def check_turn(rpc, thread_id, prompt, folder, label, plugin_root, state_root, *, repair=False):
    with (folder / f'{label}.events.jsonl').open('w') as events:
        answer = run_turn(rpc, thread_id, prompt, events=events)
    (folder / f'{label}.md').write_text(answer)
    thread = rpc.request('thread/read', {'threadId': thread_id, 'includeTurns': False})['thread']
    rows = [json.loads(line) for line in (folder / f'{label}.events.jsonl').read_text().splitlines()]
    hooks = [row['params']['run'] for row in rows if row.get('method') == 'hook/completed'
             and row['params'].get('threadId') == thread_id
             and Path(row['params']['run']['sourcePath']).is_relative_to(plugin_root)]
    turn_path = state_root / '.local/title-turns' / f'{thread_id}.json'
    title_path = state_root / '.local/titles' / f'{thread_id}.json'
    turn = json.loads(turn_path.read_text()) if turn_path.exists() else {}
    state = json.loads(title_path.read_text()) if title_path.exists() else {}
    title = thread.get('name')
    checks = {
        'three_parts': isinstance(title, str) and len(title.split('｜')) == 3 and all(title.split('｜')),
        'prompt_hook_ran': sum(h['eventName'] == 'userPromptSubmit' and h['status'] == 'completed' for h in hooks) == 1,
        'stop_hook_ran': any(h['eventName'] == 'stop' and h['status'] in ('completed', 'blocked') for h in hooks),
        'this_turn_checked': bool(turn.get('turn_id')) and state.get('checked_turn_id') == turn['turn_id'],
        'title_readback_matches': state.get('last_applied') == title,
        'cwd_has_no_local_state': not (Path(thread['cwd']) / '.local').exists(),
    }
    if repair:
        checks['one_stop_block'] = sum(h['eventName'] == 'stop' and h['status'] == 'blocked' for h in hooks) == 1
        checks['one_repair_requested'] = turn.get('repair_requested') is True
    return {'title': title, 'checks': checks, 'passed': all(checks.values()),
            'hooks': [{'event': h['eventName'], 'status': h['status']} for h in hooks]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--prepare', action='store_true', help='在全局安装前生成一个已有会话')
    mode.add_argument('--execute', action='store_true')
    parser.add_argument('--evidence', type=Path)
    args = parser.parse_args()
    if args.prepare:
        if Installer(global_mode=True).read_receipt():
            raise RuntimeError('此准备阶段须在首次全局安装前运行')
        folder = ROOT / '.local' / ('global-live-' + str(time.time_ns())); folder.mkdir()
        base = Path(tempfile.mkdtemp(prefix='clarity-global-live-')).resolve()
        plain, project = base / 'plain folder', base / 'git project'
        plain.mkdir(); project.mkdir()
        subprocess.run(['git', 'init', '-q', str(project)], check=True)
        with CodexRPC(cwd=plain, timeout=30) as rpc:
            response = start_session(rpc, plain, model='gpt-6-luna', effort='medium',
                                     ephemeral=False, sandbox='danger-full-access')
            thread_id = response['thread']['id']
            with (folder / 'before-install.events.jsonl').open('w') as events:
                answer = run_turn(rpc, thread_id, '请用一句话解释什么是缓存。', events=events)
            (folder / 'before-install.md').write_text(answer)
        save(folder / 'prepared.json', {'old_thread_id': thread_id, 'plain': str(plain),
                                       'project': str(project), 'model': 'gpt-6-luna', 'effort': 'medium'})
        print(str(folder), flush=True)
        return
    if args.evidence is None:
        parser.error('--execute 需要 --evidence 指向准备阶段的目录')
    folder = args.evidence.resolve()
    prepared = json.loads((folder / 'prepared.json').read_text())
    manager = Installer(global_mode=True)
    status = manager.status()
    if not status.get('runtime_ready'):
        raise RuntimeError('请先安装并通过官方 /hooks 审查')
    plugin_root = Path(status['skill_path']).parents[2]
    results = {'model': prepared['model'], 'effort': prepared['effort'], 'checks': {}, 'turns': {}}
    threads = [prepared['old_thread_id']]
    with CodexRPC(cwd=prepared['plain'], timeout=30) as rpc:
        try:
            # Resume in a fresh server so the old chat loads the newly installed global config.
            resumed = rpc.request('thread/resume', {'threadId': prepared['old_thread_id'],
                'cwd': prepared['plain'], 'model': prepared['model'],
                'config': {'model_reasoning_effort': prepared['effort']},
                'approvalPolicy': 'never', 'sandbox': 'danger-full-access'})
            assert resumed['model'] == prepared['model'] and resumed['reasoningEffort'] == prepared['effort']
            results['turns']['existing_non_git_chat'] = check_turn(rpc, threads[0],
                '请再用一个办公室例子解释缓存，让不写代码的同事也能理解。',
                folder, 'resumed-plain', plugin_root, manager.root)
            response = start_session(rpc, Path(prepared['project']), model=prepared['model'],
                effort=prepared['effort'], ephemeral=False, sandbox='danger-full-access')
            threads.append(response['thread']['id'])
            results['turns']['new_git_chat_repair_test'] = check_turn(rpc, threads[-1],
                '这是标题插件的漏做恢复测试：第一条最终回复前请暂不执行任何工具，'
                '先直接用一句话解释什么是缓存。随后若收到结束检查要求补做标题的反馈，'
                '再按反馈执行标题维护，完成后结束本轮。这是一次明确限定的测试。',
                folder, 'new-project', plugin_root, manager.root, repair=True)
            results['checks']['existing_and_new_across_directories'] = all(
                turn['passed'] for turn in results['turns'].values())
        finally:
            archived = []
            for thread_id in threads:
                try:
                    rpc.request('thread/archive', {'threadId': thread_id})
                    archived.append(thread_id)
                except Exception as error:
                    results.setdefault('cleanup_errors', []).append(str(error))
            results['checks']['test_chats_archived'] = len(archived) == len(threads)
            results['passed'] = all(results['checks'].values())
            save(folder / 'result.json', results)
    print(json.dumps({'folder': str(folder), **results}, ensure_ascii=False, indent=2), flush=True)
    if not results['passed']:
        raise RuntimeError('全局标题联测未全部通过，见本地记录')


if __name__ == '__main__': main()
