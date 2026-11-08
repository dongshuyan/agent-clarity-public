#!/usr/bin/env python3
"""Opt-in live model test. Creates one new persistent chat in this test project."""
import argparse
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from codex_rpc import CodexRPC
from codex_session import start_session, run_turn
from session_title import activate, TitleManager


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true', required=True)
    args = parser.parse_args()
    if not args.execute:
        return
    activate(ROOT)
    folder = ROOT / '.local' / ('title-e2e-' + str(time.time_ns()))
    folder.mkdir(parents=True)
    result = {'folder': str(folder), 'checks': {}}
    try:
        with CodexRPC(cwd=ROOT, timeout=30) as rpc:
            started = start_session(rpc, ROOT, ephemeral=False, sandbox='danger-full-access')
            thread_id = started['thread']['id']
            result.update(thread_id=thread_id, model=started['model'], effort=started['reasoningEffort'],
                          instruction_sources=started.get('instructionSources'))
            # A fresh chat may already have a native title before its first tool call.
            rpc.request('thread/name/set', {'threadId': thread_id, 'name': '缓存资料整理（初始名称测试）'})
            prompts = [
                '我要给不写代码的同事写一份库存缓存说明。假设系统把读到的库存缓存60秒；'
                '缓存有效时页面读缓存，过期后下一次读取才查数据库。修改库存只改数据库，不清缓存。'
                '先给出你准备怎么解释的思路，等我确认再写正式说明。无需联网或检查其他项目。',
                '确认。请在这里直接写正式说明，让同事理解为什么改完库存还可能看到旧数量。'
                '无需另存文档。写好就完成这项任务。',
            ]
            names = []
            for index, prompt in enumerate(prompts):
                with (folder / f'turn-{index+1}.events.jsonl').open('w') as events:
                    answer = run_turn(rpc, thread_id, prompt, events=events)
                (folder / f'turn-{index+1}.md').write_text(answer)
                name = rpc.request('thread/read', {'threadId': thread_id, 'includeTurns': False})['thread']['name']
                names.append(name)
                print(json.dumps({'turn': index+1, 'title': name}, ensure_ascii=False), flush=True)
            result['names'] = names
            result['checks']['first_turn_waiting'] = names[0].startswith('待确认｜') and len(names[0].split('｜')) == 3
            result['checks']['completion'] = names[1].startswith('已完成｜') and len(names[1].split('｜')) == 3
            if not all(result['checks'].values()):
                result['passed'] = False
                raise RuntimeError('新会话未按三段式改名；完整结果已保存在本地，请检查插件加载和调用记录')
            result['checks']['stable_topic'] = names[0].split('｜')[1] == names[1].split('｜')[1]
            manual = '我的缓存说明收藏'
            rpc.request('thread/name/set', {'threadId': thread_id, 'name': manual})
            guarded = TitleManager(ROOT, rpc, caller_thread_id=thread_id).set(
                thread_id, names[0].split('｜')[1], '实现中', ROOT, progress='补充缓存过期说明')
            result['checks']['external_change_pauses_manager'] = guarded['result'] == 'paused'
            with (folder / 'turn-3.events.jsonl').open('w') as events:
                answer = run_turn(rpc, thread_id, '再补一句：过期时如果没有读取，会不会立刻更新缓存？回答后本任务完成。', events=events)
            (folder / 'turn-3.md').write_text(answer)
            actual = rpc.request('thread/read', {'threadId': thread_id, 'includeTurns': False})['thread']['name']
            result['checks']['manual_title_preserved'] = actual == manual
        with CodexRPC(cwd=ROOT, timeout=30) as rpc:
            actual = rpc.request('thread/read', {'threadId': thread_id, 'includeTurns': False})['thread']['name']
            result['checks']['persisted_across_connections'] = actual == manual
        result['passed'] = all(result['checks'].values())
        print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
        if not result['passed']:
            raise RuntimeError('标题全流程检查失败，查看本地证据')
    finally:
        (folder / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
