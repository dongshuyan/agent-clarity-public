"""Run test turns through the same app-server protocol used by Codex clients."""
import json
import time

from codex_rpc import RPCError


def start_session(rpc, cwd, *, model='gpt-6-astra', effort='high',
                  ephemeral=True, sandbox='read-only'):
    response = rpc.request('thread/start', {
        'cwd': str(cwd), 'model': model, 'sandbox': sandbox,
        'approvalPolicy': 'never', 'ephemeral': ephemeral,
        'config': {'model_reasoning_effort': effort},
    })
    if response.get('model') != model or response.get('reasoningEffort') != effort:
        raise RPCError('实际模型或推理档位与测试配置不一致')
    return response


def run_turn(rpc, thread_id, prompt, *, schema=None, events=None, timeout=600):
    params = {'threadId': thread_id, 'input': [{'type': 'text', 'text': prompt}]}
    if schema is not None:
        params['outputSchema'] = schema
    response = rpc.request('turn/start', params)
    turn_id = response['turn']['id']
    deadline = time.monotonic() + timeout
    messages = []
    try:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RPCError('模型回合超时')
            event = rpc.next_event(timeout=remaining)
            if events is not None:
                events.write(json.dumps(event, ensure_ascii=False) + '\n')
                events.flush()
            # Tests never approve commands, supply credentials, or answer user-input requests.
            if 'id' in event and 'method' in event:
                rpc._send({'id': event['id'], 'error': {
                    'code': -32601, 'message': 'Interactive requests are unsupported in this test run'}})
                continue
            payload = event.get('params', {})
            if payload.get('threadId') != thread_id or payload.get('turnId', turn_id) != turn_id:
                continue
            if event.get('method') == 'item/completed' and payload.get('turnId') == turn_id:
                item = payload.get('item', {})
                if (item.get('type') == 'agentMessage' and item.get('phase') == 'final_answer'
                        and item.get('text')):
                    messages.append(item['text'])
            if event.get('method') == 'turn/completed' and payload.get('turn', {}).get('id') == turn_id:
                turn = payload['turn']
                if turn.get('status') != 'completed':
                    raise RPCError('模型回合未完成', turn.get('error'))
                if not messages:
                    raise RPCError('模型回合没有最终文字输出')
                return messages[-1]
    except (RPCError, OSError, ValueError, KeyboardInterrupt):
        # Do not leave an abandoned test generating in the background.
        try:
            rpc.request('turn/interrupt', {'threadId': thread_id, 'turnId': turn_id})
        except RPCError:
            pass
        raise
