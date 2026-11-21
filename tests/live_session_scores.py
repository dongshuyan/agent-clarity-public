#!/usr/bin/env python3
"""Opt-in installed-plugin checks using a named test model at low effort."""
import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import tomllib
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO/'scripts'))
import title_plugin
from codex_rpc import CodexRPC


def check_reference_title(case, catalog_source):
    """Validate the actual title for a completed ordinary reference-mode turn."""
    metrics, result = case['metrics'], case['score_result']
    prefix = case['title'].split('｜', 1)[0]
    assert result['level'] == 'S2'
    if metrics['input_observed']:
        assert metrics['window_metadata']['source'] in ('hook', catalog_source)
        assert result['score_status'] == 'scored' and prefix == f"S2·{result['score']}分"
    else:
        assert result['score_status'] == 'insufficient_data' and result['score'] is None
        baseline = result.get('baseline')
        if baseline is None:
            assert prefix == '未评分'
        else:
            assert metrics['last_input_tokens'] is not None and baseline['level'] == 'S1'
            assert prefix == f"S1·{baseline['score']}分（窗口未知）"


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute',action='store_true',required=True)
    parser.add_argument('--model', default='gpt-6-luna',
                        help='Test model available to this account (default: gpt-6-luna).')
    args=parser.parse_args()
    runs=REPO/'.local/live-session-scores'
    runs.mkdir(parents=True,exist_ok=True)
    evidence=Path(tempfile.mkdtemp(prefix='run-',dir=runs))
    # Use a fixture inside the already trusted workspace. CLI overrides cannot
    # grant project trust: Codex checks the persisted trust boundary separately.
    workspace=Path(tempfile.mkdtemp(prefix='workspace-',dir=evidence)).resolve()
    subprocess.run(['git','init','-q',str(workspace)],check=True)
    cli=shutil.which('codex')
    trust=f'projects.{json.dumps(str(workspace))}.trust_level="trusted"'
    # Trust applies only to this controlled test subprocess, not user settings.
    def client(**kwargs):
        kwargs.pop('local_only',None)
        return CodexRPC(command=[cli,'app-server','--stdio','-c',trust],**kwargs)
    manager=title_plugin.Installer(workspace)
    home=Path(os.environ.get('CODEX_HOME',str(Path.home()/'.codex'))).resolve()
    user_config=home/'config.toml'
    def user_projects():
        return tomllib.loads(user_config.read_text()).get('projects',{}) if user_config.exists() else {}
    assert str(workspace) not in user_projects()
    with CodexRPC(cwd=workspace,timeout=20,local_only=True) as rpc:
        rpc.request('config/value/write',{'keyPath':'projects','value':{str(workspace):{'trust_level':'trusted'}},
            'mergeStrategy':'upsert','filePath':str(user_config)})
    try:
        record=manager.install()
    except Exception:
        with CodexRPC(cwd=workspace,timeout=20,local_only=True) as rpc:
            remaining=user_projects();remaining.pop(str(workspace),None)
            rpc.request('config/value/write',{'keyPath':'projects','value':remaining,
                'mergeStrategy':'replace','filePath':str(user_config)})
        raise
    plugin_root=Path(record['skill_path']).parents[2]
    score_script=plugin_root/'scripts/session_score.py'
    report={'model':args.model,'effort':'low','workspace':str(workspace),
            'plugin_id':record['plugin_id'],'version':record['version'],'cases':[]}
    thread_ids=[]
    with CodexRPC(cwd=workspace,timeout=15,local_only=True) as rpc:
        other_plugins=rpc.request('config/read',{'cwd':str(workspace),'includeLayers':False})['config'].get('plugins',{})
    selected={pid:{'enabled':False} for pid in other_plugins}
    selected[manager.plugin_id]={'enabled':True}
    # CLI key-path overrides split on dots and do not decode quoted segments.
    # Replace the whole TOML table so plugin IDs remain actual keys.
    table='{'+','.join(json.dumps(pid)+'={enabled='+('true' if v['enabled'] else 'false')+'}'
                       for pid,v in selected.items())+'}'
    only_this_plugin=['-c','plugins='+table]
    with CodexRPC(command=[cli,'app-server','--stdio',*only_this_plugin],cwd=workspace,timeout=20) as rpc:
        listed=rpc.request('hooks/list',{'cwds':[str(workspace)]})
        enabled=[h for e in listed['data'] for h in e['hooks'] if h.get('enabled')]
        assert len(enabled)==7 and all(h.get('pluginId')==manager.plugin_id for h in enabled),enabled

    def configure(*args):
        env=dict(os.environ);env.pop('CODEX_THREAD_ID',None)
        return subprocess.run([sys.executable,str(score_script),'configure','--project',str(workspace),*args],
                              env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,check=True)

    def run(label, *, resume=None, prompt_text=None):
        path=evidence/(label+'.events.jsonl')
        cmd=[cli,'--no-daemon','--dangerously-bypass-hook-trust',
             'exec','-c','project_doc_max_bytes=0','--json',*only_this_plugin,
             '--sandbox','danger-full-access','-m',args.model,
             '-c','model_reasoning_effort="low"','-C',str(workspace)]
        prompt = prompt_text or (
            '这是已授权的本地插件测试。请用一句话解释缓存；仅执行已启用的标题核对，'
            '不修改其他文件。')
        if resume:
            # Resume's own parser has no -C; the global exec -C above supplies it.
            cmd+=['resume',resume,prompt]
        else:
            cmd+=[prompt]
        with path.open('w') as out,(evidence/(label+'.stderr.txt')).open('w') as err:
            result=subprocess.run(cmd,stdout=out,stderr=err,timeout=150)
        rows=[json.loads(line) for line in path.read_text().splitlines() if line.strip()]
        tid=next((r['thread_id'] for r in rows if r.get('type')=='thread.started'),resume)
        if tid and tid not in thread_ids:thread_ids.append(tid)
        if result.returncode or not tid:
            raise RuntimeError(f'{label}: CLI failed; see {evidence}')
        with CodexRPC(cwd=workspace,timeout=15,local_only=True) as rpc:
            thread=rpc.request('thread/read',{'threadId':tid,'includeTurns':False})['thread']
        assert thread['model']==args.model and thread['reasoningEffort']=='low'
        state=json.loads((workspace/'.local/title-scores'/f'{tid}.json').read_text())
        case={'label':label,'thread_id':tid,'title':thread.get('name'),
              'score_result':state.get('score_result'),'metrics':state.get('metrics'),
              'pending_probe':state.get('pending_probe'),
              'cli_exit':result.returncode}
        report['cases'].append(case)
        (evidence/'result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
        print(json.dumps(case,ensure_ascii=False),flush=True)
        return tid,case

    try:
        # Strict mode scores only when this host actually supplied a usable window.
        configure('--level','S2','--window-mode','actual_only')
        tid,strict=run('strict-s2')
        if strict['metrics']['input_observed']:
            assert strict['metrics']['window_metadata']['source']=='hook'
            assert strict['score_result']['score_status']=='scored' and strict['title'].startswith('S2·')
        else:
            assert strict['score_result']['score_status']=='insufficient_data'
            assert str(strict['title']).startswith('未评分｜')

        configure('--level','S1')
        tid,s1=run('resumed-s1',resume=tid)
        assert s1['score_result']['level']=='S1' and s1['score_result']['score_status']=='scored'
        assert s1['title'].startswith('S1·')
        assert s1['metrics']['round_count']==2

        # Explicit opt-in affects only this synthetic test installation.
        configure('--level','S2','--window-mode','reference')
        tid,s2=run('resumed-s2-reference',resume=tid)
        assert s2['metrics']['round_count']==3
        account_config = tomllib.loads(user_config.read_text()) if user_config.exists() else {}
        source = 'reference_catalog' if 'model_catalog_json' in account_config else 'reference_cache'
        check_reference_title(s2, source)

        with CodexRPC(cwd=workspace,timeout=15,local_only=True) as rpc:
            parts=s2['title'].split('｜');parts[-1]='用户保留的进展'
            rpc.request('thread/name/set',{'threadId':tid,'name':'｜'.join(parts)})
        tid,manual=run('manual-progress',resume=tid)
        assert manual['title'].endswith('｜用户保留的进展')

        configure('--enabled','off')
        tid,disabled=run('disabled-score',resume=tid)
        assert not disabled['title'].startswith(('S1·','S2·','未评分｜'))
        assert disabled['score_result']['score_status']=='disabled'

        probe_prompt = (
            '这是已授权的本地插件联测。请正常完成一句话缓存解释，并执行标题核对。'
            '如果系统提示本轮需要会话切换评分，请在最终答复前严格按提示执行本地 semantic-submit，'
            '不要把 JSON 或评分过程写入给用户的正文。')

        # Fresh S3 thread: rounds 1–2 are deterministic; round 3 probes and
        # round 4 must publish the current deterministic S2 result.
        configure('--enabled','on','--level','S3','--window-mode','reference')
        s3_tid = None
        s3_cases = []
        for index in range(1, 5):
            s3_tid, s3_case = run(f's3-turn-{index}', resume=s3_tid,
                                  prompt_text=probe_prompt)
            s3_cases.append(s3_case)
        assert s3_cases[2]['score_result']['level'] == 'S3'
        assert s3_cases[2]['pending_probe'] is None
        assert s3_cases[2]['title'].startswith(('S3·', '未评分｜'))
        check_reference_title(s3_cases[3], source)

        # Fresh S4 thread: the fifth root round probes with bounded history.
        configure('--level','S4','--window-mode','reference')
        s4_tid = None
        s4_cases = []
        for index in range(1, 6):
            s4_tid, s4_case = run(f's4-turn-{index}', resume=s4_tid,
                                  prompt_text=probe_prompt)
            s4_cases.append(s4_case)
        assert s4_cases[4]['score_result']['level'] == 'S4'
        assert s4_cases[4]['pending_probe'] is None
        assert s4_cases[4]['title'].startswith(('S4·', '未评分｜'))
        report['passed']=True
    finally:
        report['archived_test_chats']=[]
        with CodexRPC(cwd=workspace,timeout=15,local_only=True) as rpc:
            for tid in thread_ids:
                try:
                    rpc.request('thread/archive',{'threadId':tid})
                    report['archived_test_chats'].append(tid)
                except Exception as error:
                    report.setdefault('cleanup_errors',[]).append(type(error).__name__)
        report['uninstall']=manager.uninstall()
        remaining=user_projects()
        if remaining.get(str(workspace))=={'trust_level':'trusted'}:
            remaining.pop(str(workspace))
            with CodexRPC(cwd=workspace,timeout=20,local_only=True) as rpc:
                rpc.request('config/value/write',{'keyPath':'projects','value':remaining,
                    'mergeStrategy':'replace','filePath':str(user_config)})
            report['fixture_trust_removed']=str(workspace) not in user_projects()
        (evidence/'result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print(json.dumps({'passed':report.get('passed',False),'evidence':str(evidence)},ensure_ascii=False))


if __name__=='__main__':main()
