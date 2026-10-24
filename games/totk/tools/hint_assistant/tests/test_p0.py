"""The P0 additions, offline: the guide target (no model), press sequences and the action budget."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from totk_hint import config, harness, live, prompts, service


class SequenceTests(unittest.TestCase):
    def test_steps_are_filled_in_and_checked(self):
        steps = live.checked_steps([{'button': 'a'}, {'button': 'down', 'duration_ms': 500, 'wait_ms': 0}])
        self.assertEqual(steps, [{'button': 'a', 'duration_ms': 150, 'wait_ms': 150},
                                 {'button': 'down', 'duration_ms': 500, 'wait_ms': 0}])

    def test_a_bad_sequence_is_rejected_before_the_game_is_asked(self):
        bad = ([], [{'button': 'nope'}], [{'button': 'a', 'duration_ms': 5}], [{'button': 'a', 'wait_ms': 2000}],
               [{'button': 'a'}] * 9, 'a', None)
        for value in bad:
            with self.assertRaises(ValueError):
                live.checked_steps(value)
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                live.call('sequence', steps=[{'button': 'a'}] * 9, folder=tmp)
            self.assertFalse((Path(tmp) / 'runtime-request.json').exists())


class BudgetTests(unittest.TestCase):
    def test_default_and_validation(self):
        self.assertEqual(copy.deepcopy(config.DEFAULTS)['action_limit'], 6)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'assistant.json'
            for bad in (0, 41, True, '6', 2.5):
                path.write_text(json.dumps({'action_limit': bad}))
                with self.assertRaises(ValueError):
                    config.load(path)
            path.write_text(json.dumps({'action_limit': 12}))
            self.assertEqual(config.load(path)['action_limit'], 12)

    def test_prompt_states_the_budget_and_the_tools(self):
        text = prompts.user_prompt(1, '帮我按一下', actions=True, action_limit=6)
        self.assertIn('最多 6 次', text)
        self.assertIn('press_sequence', text)
        self.assertIn('changes', text)
        denied = prompts.user_prompt(1, '你好')
        self.assertIn('没有 press_button / press_sequence 工具', denied)
        self.assertNotIn('本次允许操作游戏', denied)


class GuideTests(unittest.TestCase):
    def harness(self):
        return harness.Harness(config=copy.deepcopy(config.DEFAULTS))

    def test_a_main_quest_target_wins_over_a_nearer_side_quest(self):
        log = {'link_xyz': [0, 0, 0], 'active': [
            {'quest': '支线', 'type': '支线任务', 'step': 'A', 'targets': [{'xyz': [0, 0, -10]}]},
            {'quest': '主线', 'type': '主要任务', 'step': 'B', 'targets': [{'xyz': [0, 0, -400], 'near': '希多'}]}]}
        with patch.object(harness.Harness, 'quest_log', return_value=log):
            target = self.harness().guide()
        self.assertEqual(target['quest'], '主线')
        self.assertEqual(target['name'], '希多')
        self.assertEqual(target['distance_m'], 400)

    def test_the_nearest_side_quest_target_wins_within_one_kind(self):
        log = {'link_xyz': [0, 0, 0], 'active': [
            {'quest': '远', 'type': '支线任务', 'step': 'A', 'targets': [{'xyz': [0, 0, -900]}]},
            {'quest': '近', 'type': '支线任务', 'step': 'A', 'targets': [{'xyz': [30, 0, 40]}]}]}
        with patch.object(harness.Harness, 'quest_log', return_value=log):
            target = self.harness().guide()
        self.assertEqual(target['quest'], '近')
        self.assertEqual(target['distance_m'], 50)

    def test_no_targets_means_no_arrow(self):
        with patch.object(harness.Harness, 'quest_log', return_value={'active': []}):
            self.assertIsNone(self.harness().guide())


class GuideChannelTests(unittest.TestCase):
    def service(self, folder):
        return service.Service(copy.deepcopy(config.DEFAULTS), folder=folder, log=lambda text: None)

    def test_the_reply_is_written_without_a_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            svc = self.service(tmp)
            with patch.object(harness.Harness, 'guide',
                              return_value={'name': '希多', 'xyz': [0, 0, -300], 'distance_m': 300}):
                svc.guide({'id': 'g1'})
            reply = json.loads((Path(tmp) / service.GUIDE_RESPONSE).read_text())
        self.assertEqual(reply['id'], 'g1')
        self.assertTrue(reply['ok'])
        self.assertEqual(reply['target']['name'], '希多')

    def test_a_missing_save_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            svc = self.service(tmp)
            with patch.object(harness.Harness, 'guide', side_effect=RuntimeError('找不到存档')):
                svc.guide({'id': 'g2'})
            reply = json.loads((Path(tmp) / service.GUIDE_RESPONSE).read_text())
        self.assertFalse(reply['ok'])
        self.assertIn('找不到存档', reply['error'])


class ToolListTests(unittest.TestCase):
    def test_press_sequence_needs_the_players_consent(self):
        allowed = harness.Harness(config=copy.deepcopy(config.DEFAULTS), allow_actions=True)
        self.assertIn('press_sequence', [spec['name'] for spec in allowed.tool_specs()])
        denied = harness.Harness(config=copy.deepcopy(config.DEFAULTS))
        self.assertNotIn('press_sequence', [spec['name'] for spec in denied.tool_specs()])
        with self.assertRaises(harness.ToolError):
            denied.call('press_sequence', {'steps': [{'button': 'a'}]})

    def test_the_budget_reaches_the_runtime_call(self):
        allowed = harness.Harness(config=copy.deepcopy(config.DEFAULTS), allow_actions=True)
        with patch.object(live, 'call', return_value={'ok': True, 'state': {}}) as call:
            allowed.call('press_sequence', {'steps': [{'button': 'a', 'duration_ms': 40, 'wait_ms': 10}]})
        self.assertEqual(call.call_args[0][0], 'sequence')
        self.assertEqual(call.call_args[1]['steps'], [{'button': 'a', 'duration_ms': 40, 'wait_ms': 10}])


if __name__ == '__main__':
    unittest.main()
