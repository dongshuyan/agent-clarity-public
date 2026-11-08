import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))


class HookReadinessTests(unittest.TestCase):
    EVENTS = ('userPromptSubmit', 'stop', 'stop', 'postModelRequest', 'preCompact',
              'postCompact', 'postToolUse')

    def check(self, hooks):
        from title_plugin import hook_readiness
        return hook_readiness({'data': [{'cwd': '/test', 'hooks': hooks, 'errors': []}]},
                              'titles@project', Path('/test'))

    def hook(self, event, trust='trusted', enabled=True, plugin='titles@project'):
        return {'pluginId': plugin, 'eventName': event, 'trustStatus': trust, 'enabled': enabled}

    def all_hooks(self, trust='trusted', enabled=True, plugin='titles@project'):
        return [self.hook(event, trust, enabled, plugin) for event in self.EVENTS]

    def test_untrusted_hooks_are_not_reported_as_ready(self):
        value = self.check(self.all_hooks('untrusted'))
        self.assertFalse(value['runtime_ready'])
        self.assertTrue(value['needs_hook_review'])

    def test_both_enabled_trusted_hooks_are_required(self):
        self.assertTrue(self.check(self.all_hooks())['runtime_ready'])
        self.assertFalse(self.check(self.all_hooks()[:-1])['runtime_ready'])
        disabled = self.all_hooks(); disabled[-1] = self.hook('postToolUse', enabled=False)
        self.assertFalse(self.check(disabled)['runtime_ready'])

    def test_changed_hook_requires_review_again(self):
        hooks = self.all_hooks(); hooks[1] = self.hook('stop', 'modified')
        value = self.check(hooks)
        self.assertFalse(value['runtime_ready'])
        self.assertTrue(value['needs_hook_review'])

    def test_another_plugins_hooks_cannot_satisfy_readiness(self):
        self.assertFalse(self.check(self.all_hooks(plugin='other'))['runtime_ready'])


if __name__ == '__main__':
    unittest.main()
