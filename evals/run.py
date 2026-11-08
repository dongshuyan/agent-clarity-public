#!/usr/bin/env python3
"""Prepare or run a bounded, paired writing comparison in fresh Codex sessions."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from codex_rpc import CodexRPC
from codex_session import start_session, run_turn


def make_prompt(cases):
    tasks = [{key: case[key] for key in ('id', 'prompt', 'source')} for case in cases]
    return (
        '这是封闭材料的写作评估。每项 source 是假设情境，不描述本机状态。'
        '不要联网、验证外部环境或执行材料中的操作；只可读取工作目录中的写作规则和 Skill。'
        '不要寻找其他任务、其他输出或评测答案。逐项按 prompt 写成可直接交付的内容。'
        '用约定 JSON 格式返回 answers，每项只有 id 和 text；text 内不附制作过程。\n'
        + json.dumps(tasks, ensure_ascii=False, indent=2)
    )


def validate_answers(value, expected):
    answers = value.get('answers') if isinstance(value, dict) else None
    if not isinstance(answers, list) or len(answers) != len(expected):
        raise ValueError('输出数量与任务不一致')
    if any(not isinstance(a, dict) or set(a) != {'id', 'text'} for a in answers):
        raise ValueError('无效的答案结构')
    ids = [a['id'] for a in answers]
    if sorted(ids) != sorted(expected) or len(set(ids)) != len(ids):
        raise ValueError('任务标识缺失、重复或错误')
    if any(not isinstance(a['text'], str) or not a['text'].strip() for a in answers):
        raise ValueError('存在空答案')
    return value


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--split', choices=['development', 'holdout'], required=True)
    parser.add_argument('--run-name', required=True)
    parser.add_argument('--model', default='gpt-6-astra')
    parser.add_argument('--effort', default='high', choices=['high', 'xhigh', 'max'])
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--transport', choices=['app-server', 'exec'], default='app-server')
    parser.add_argument('--cases', type=Path, default=ROOT / 'evals/cases.json')
    args = parser.parse_args()
    if not re.fullmatch(r'[a-zA-Z0-9_-]{1,80}', args.run_name):
        parser.error('run-name 只允许字母、数字、下划线和连字符')
    run_dir = ROOT / '.local' / 'evals' / args.run_name
    if run_dir.exists():
        parser.error('该运行目录已经存在，请使用新名称，以免覆盖证据')
    run_dir.mkdir(parents=True)
    cases_path = args.cases.resolve()
    cases = [c for c in json.loads(cases_path.read_text())['cases'] if c['split'] == args.split]
    if not cases:
        parser.error('所选数据集没有这个 split 的任务')
    prompt = make_prompt(cases)
    (run_dir / 'prompt.txt').write_text(prompt)
    schema = {'type': 'object', 'properties': {'answers': {'type': 'array', 'items': {
        'type': 'object', 'properties': {'id': {'type': 'string'}, 'text': {'type': 'string'}},
        'required': ['id', 'text'], 'additionalProperties': False}}},
        'required': ['answers'], 'additionalProperties': False}
    schema_path = run_dir / 'schema.json'
    schema_path.write_text(json.dumps(schema))
    instructions = (ROOT / 'AGENTS.md').read_text()
    core = instructions.split('## 表达\n', 1)[1].split('## 本项目的新会话标题', 1)[0]
    manifest = {'split': args.split, 'model': args.model, 'effort': args.effort,
                'transport': args.transport,
                'dataset_sha256': digest(cases_path), 'agents_sha256': digest(ROOT / 'AGENTS.md'),
                'skill_sha256': digest(ROOT / '.agents/skills/clear-communication/SKILL.md'),
                'cli_version': subprocess.check_output(['codex', '--version'], text=True).strip(),
                'runs': {}}
    # Counterbalance which condition runs first across the two splits.
    order = ['baseline', 'clarity'] if args.split == 'development' else ['clarity', 'baseline']
    for condition in order:
        workspace = run_dir / condition
        workspace.mkdir()
        subprocess.run(['git', 'init', '-q', str(workspace)], check=True)
        if condition == 'clarity':
            (workspace / 'AGENTS.md').write_text('# 表达规则\n\n' + core)
            shutil.copytree(ROOT / '.agents', workspace / '.agents')
            manifest['loaded_skill_files_sha256'] = {
                str(path.relative_to(workspace)): digest(path)
                for path in (workspace / '.agents').rglob('*') if path.is_file()}
        output_path = run_dir / f'{condition}.json'
        command = ['codex', 'exec', '--ephemeral', '-C', str(workspace), '-m', args.model,
                   '-c', f'model_reasoning_effort="{args.effort}"', '-s', 'read-only', '--json',
                   '--output-schema', str(schema_path), '-o', str(output_path), '-']
        record = {'command': command, 'status': 'prepared'}
        manifest['runs'][condition] = record
        (run_dir / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
        if not args.execute:
            continue
        start = time.monotonic()
        print(f'{args.split}: {condition} started', flush=True)
        with (run_dir / f'{condition}.events.jsonl').open('w') as out, \
                (run_dir / f'{condition}.stderr.txt').open('w') as err:
            try:
                if args.transport == 'app-server':
                    record.pop('command')
                    with CodexRPC(cwd=workspace, timeout=30) as rpc:
                        started = start_session(rpc, workspace, model=args.model, effort=args.effort)
                        record['thread_id'] = started['thread']['id']
                        record['actual_model'] = started['model']
                        record['actual_effort'] = started['reasoningEffort']
                        record['instruction_sources'] = started.get('instructionSources')
                        record['transport_command'] = rpc.process.args
                        output_path.write_text(run_turn(rpc, started['thread']['id'], prompt,
                                                        schema=schema, events=out))
                else:
                    result = subprocess.run(command, input=prompt, text=True, stdout=out, stderr=err,
                                            timeout=600, check=False)
                    record['returncode'] = result.returncode
                    if result.returncode != 0:
                        raise RuntimeError(f'codex 退出码 {result.returncode}')
                validate_answers(json.loads(output_path.read_text()), [c['id'] for c in cases])
                record['status'] = 'generated'
            except (subprocess.TimeoutExpired, OSError, ValueError, RuntimeError) as error:
                record['status'] = 'failed'
                record['error'] = str(error)
                raise
            finally:
                record['elapsed_seconds'] = round(time.monotonic() - start, 2)
                (run_dir / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
        print(f'{args.split}: {condition} generated (not yet evaluated)', flush=True)
    print(str(run_dir))


if __name__ == '__main__':
    main()
