import io
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from codex_rpc import RPCError
from codex_session import run_turn, start_session


class SessionTests(unittest.TestCase):
    class Client:
        def __init__(self, events=()):
            self.events = iter(events)
            self.calls = []

        def request(self, method, params):
            self.calls.append((method, params))
            return {'turn': {'id': 'turn-1'}, 'model': 'wrong-model', 'reasoningEffort': 'high'}

        def next_event(self, **kwargs):
            try:
                return next(self.events)
            except StopIteration:
                raise RPCError('timeout')

    def event(self, method, **payload):
        return {'method': method, 'params': {'threadId': 'thread-1', 'turnId': 'turn-1', **payload}}

    def test_model_mismatch_cannot_be_reported_as_requested_model(self):
        with self.assertRaises(RPCError):
            start_session(self.Client(), Path.cwd())

    def test_completed_message_and_matching_turn_are_required(self):
        client = self.Client([
            self.event('item/completed', item={'type': 'agentMessage', 'phase': 'final_answer', 'text': 'answer'}),
            self.event('turn/completed', turn={'id': 'other', 'status': 'completed'}),
            self.event('turn/completed', turn={'id': 'turn-1', 'status': 'completed'}),
        ])
        self.assertEqual(run_turn(client, 'thread-1', 'prompt', events=io.StringIO()), 'answer')

    def test_commentary_is_never_a_final_answer(self):
        completed = self.event('turn/completed', turn={'id': 'turn-1', 'status': 'completed'})
        commentary = self.event('item/completed', item={
            'type': 'agentMessage', 'phase': 'commentary', 'text': 'working'})
        for events in [[commentary, completed], [self.event('item/completed', item={
                'type': 'agentMessage', 'phase': None, 'text': 'ambiguous'}), completed]]:
            with self.assertRaises(RPCError):
                run_turn(self.Client(events), 'thread-1', 'prompt')
        final = self.event('item/completed', item={
            'type': 'agentMessage', 'phase': 'final_answer', 'text': 'answer'})
        other_turn = self.event('item/completed', turnId='turn-other', item={
            'type': 'agentMessage', 'phase': 'final_answer', 'text': 'unrelated'})
        self.assertEqual(run_turn(self.Client([final, commentary, other_turn, completed]),
                                  'thread-1', 'prompt'), 'answer')

    def test_failure_and_timeout_interrupt_without_returning_partial_text(self):
        for events in [[], [self.event('turn/completed', turn={'id': 'turn-1', 'status': 'failed'})]]:
            client = self.Client(events)
            with self.assertRaises(RPCError):
                run_turn(client, 'thread-1', 'prompt')
            self.assertEqual(client.calls[-1][0], 'turn/interrupt')

    def test_user_cancellation_interrupts_the_model_turn(self):
        client = self.Client()
        def cancelled(**kwargs):
            raise KeyboardInterrupt()
        client.next_event = cancelled
        with self.assertRaises(KeyboardInterrupt):
            run_turn(client, 'thread-1', 'prompt')
        self.assertEqual(client.calls[-1][0], 'turn/interrupt')


if __name__ == '__main__':
    unittest.main()
