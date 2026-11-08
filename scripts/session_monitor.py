#!/usr/bin/env python3
"""Operate the installed session monitor without depending on its cache path."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path)
    args, forwarded = parser.parse_known_args()
    if not forwarded:
        forwarded = ['status']
    home = Path(os.environ.get('CODEX_HOME', str(Path.home()/'.codex'))).resolve()
    shared = Path.home()/'Library/Application Support/Agent Clarity/codex/agent-clarity'
    roots = [args.project.resolve()] if args.project else [shared, home/'agent-clarity']
    for root in roots:
        receipt = root/'.local/agent-clarity/plugin.json'
        if not receipt.is_file():
            continue
        value = json.loads(receipt.read_text())
        if not value.get('enabled'):
            continue
        skill = value.get('skill_path')
        if not isinstance(skill, str) or not Path(skill).is_absolute():
            raise ValueError('安装记录缺少有效的 skill_path')
        script = Path(skill).parents[2]/'scripts/session_score.py'
        if not script.is_file():
            raise ValueError('当前安装没有 S1–S4 评分脚本，请先更新至 0.7.0')
        scope = ['--project', str(root)] if args.project else ['--global']
        return subprocess.run([sys.executable, str(script), *forwarded, *scope]).returncode
    raise ValueError('未找到已启用的插件安装')


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (ValueError, OSError) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1)
