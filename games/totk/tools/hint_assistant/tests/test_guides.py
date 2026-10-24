"""guides.py and the guide tool, offline: the web pages, the game's tables, the live state and the save are fakes."""
import io
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
import urllib.error
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from totk_hint import backends, guides, harness

WIKITEXT = ("{{Infobox|name=Jirutagumac Shrine}}The '''Jirutagumac Shrine''' is a [[Shrine of Light]] in "
            "[[Tears of the Kingdom|TotK]].<ref>Guide</ref>\n==Themes and Navigation==\n"
            "By merging a [[Wing]] onto a [[Cart]], Link can create a vehicle. [[File:Map.png|thumb]]" + ' Fan.' * 60)
SAMURAI = ('<html><nav>menu</nav><div class="entry-content"><p>This page explains everything.</p>'
           '<h2>Jirutagumac Shrine Walkthrough for The Legend of Zelda</h2><ol><li>Go left.</li>'
           '<li>Grab the wings with Ultrahand.</li></ol>' + '<p>Attach the fan.</p>' * 30 +
           '<script>var x=1;</script></div><footer>links</footer></html>')
IGN = ('<html><h2><span class="mw-headline" id="Location">Location</span></h2><p>skip</p>'
       '<h2><span class="mw-headline" id="Walk">Jirutagumac Shrine Walkthrough</span></h2>'
       '<p>Place a wing using Ultrahand on the right ramp.</p>' + '<p>Attach a Cart &amp; a Fan.</p>' * 20 +
       '<p>Click or tap here to return to the rest of the Shrine Guides.</p></html>')


def fake_get(pages):
    def get(url, timeout):
        for part, body in pages.items():
            if part in url:
                if isinstance(body, Exception):
                    raise body
                return body
        raise urllib.error.HTTPError(url, 404, 'Not Found', {}, io.BytesIO())
    return get


class GuideFetchTests(unittest.TestCase):
    def setUp(self):
        self.cache = tempfile.TemporaryDirectory()
        self.addCleanup(self.cache.cleanup)

    def test_three_sources_cleaned_and_cached(self):
        pages = {'zeldawiki.wiki': json.dumps({'parse': {'wikitext': WIKITEXT}}),
                 'samurai-gamers.com/zelda-tears-of-the-kingdom/jirutagumac-shrine-walkthrough': SAMURAI,
                 'ign.com/wikis/the-legend-of-zelda-tears-of-the-kingdom/Jirutagumac_Shrine': IGN}
        with patch.object(guides, '_get', side_effect=fake_get(pages)) as get:
            got = guides.fetch('Jirutagumac Shrine', cache=self.cache.name)
        self.assertEqual([p['source'] for p in got], ['Zelda Wiki', 'Samurai Gamers', 'IGN'])
        wiki, samurai, ign = (p['text'] for p in got)
        self.assertIn('Jirutagumac Shrine is a Shrine of Light in TotK.', wiki)
        self.assertIn('merging a Wing onto a Cart', wiki)
        for markup in ('{{', '[[', '<ref', "'''", 'File:'):
            self.assertNotIn(markup, wiki)
        self.assertTrue(samurai.startswith('Jirutagumac Shrine Walkthrough for'))   # past the intro
        self.assertIn('Grab the wings with Ultrahand.', samurai)
        self.assertNotIn('var x', samurai)
        self.assertTrue(ign.startswith('Jirutagumac Shrine Walkthrough'))   # the location section is skipped
        self.assertIn('Attach a Cart & a Fan.', ign)
        self.assertNotIn('Click or tap', ign)
        self.assertEqual(got[2]['url'], 'https://www.ign.com/wikis/the-legend-of-zelda-tears-of-the-kingdom/Jirutagumac_Shrine')
        self.assertEqual(get.call_count, 3)
        with patch.object(guides, '_get', side_effect=AssertionError('the cache answers')):
            self.assertEqual(guides.fetch('Jirutagumac Shrine', cache=self.cache.name), got)

    def test_blocked_or_missing_sources_are_left_out_and_nothing_is_cached_empty(self):
        blocked = urllib.error.HTTPError('u', 403, 'Forbidden', {}, io.BytesIO())
        pages = {'zeldawiki.wiki': json.dumps({'error': {'code': 'missingtitle'}}), 'samurai-gamers.com': blocked,
                 'ign.com': IGN}
        with patch.object(guides, '_get', side_effect=fake_get(pages)):
            got = guides.fetch('Jirutagumac Shrine', cache=self.cache.name)
        self.assertEqual([p['source'] for p in got], ['IGN'])
        with patch.object(guides, '_get', side_effect=fake_get({})):
            self.assertEqual(guides.fetch('Nowhere Shrine', cache=self.cache.name), [])
        self.assertFalse((Path(self.cache.name) / 'Nowhere_Shrine.json').exists())

    def test_stale_cache_is_fetched_again(self):
        path = Path(self.cache.name) / 'Jirutagumac_Shrine.json'
        old = [{'source': 'IGN', 'url': 'u', 'text': 'old'}]
        path.write_text(json.dumps({'time': time.time() - guides.MAX_AGE - 1, 'pages': old}))
        with patch.object(guides, '_get', side_effect=fake_get({'ign.com': IGN})):
            got = guides.fetch('Jirutagumac Shrine', cache=self.cache.name)
        self.assertNotEqual(got, old)


def tables(names, quests=None, locations=None, items=None):
    quests = quests or {}
    return Mock(names=names, by_name={k: {} for k in quests}, challenges=[{'name': k} for k in quests],
                locations=locations or [], items=items or {}, place_name=lambda k: names.get(k),
                quest_name=lambda k: quests.get(k))


class GuideToolTests(unittest.TestCase):
    def setUp(self):
        self.h = harness.Harness({})
        locations = [{'key': 'Dungeon045', 'category': 'Shrine', 'field': 'MainField', 'pos': [[1000.0, 1500.0, -2000.0]]},
                     {'key': 'Dungeon001', 'category': 'Shrine', 'field': 'MainField', 'pos': [[-500.0, 100.0, 300.0]]}]
        self.h._tables = tables({'Dungeon045': '吉鲁塔古马奇神庙', 'Dungeon001': '乌奇神庙', 'Village': '卡卡利科村'},
                                {'Sub_Quest': '迷路的小孩'}, locations,
                                {'SpObj_LiftGeneratorWing_Capsule_A_01': '翼', 'SpObj_Cart_Capsule_A_01': '平台车',
                                 'Obj_ReverseRecorder': '倒转乾坤', 'Weapon_Sword_001': '旅人之剑〔按键〕', 'Fan': '风扇机'})
        self.h._tables_en = tables({'Dungeon045': 'Jirutagumac Shrine', 'Dungeon001': 'Ukouh Shrine', 'Village': 'Kakariko Village'},
                                   {'Sub_Quest': 'The Lost Child'}, items={
                                       'SpObj_LiftGeneratorWing_Capsule_A_01': 'Wing', 'SpObj_Cart_Capsule_A_01': 'Cart',
                                       'Obj_ReverseRecorder': 'Recall', 'Fan': 'Fan'})
        self.fetched = []
        patcher = patch.object(guides, 'fetch', side_effect=lambda name, **kw: self.fetched.append(name) or
                               [{'source': 'IGN', 'url': 'u', 'text': f'how to solve {name}: put two wings on a Cart, '
                                                                     f'then Recall it. Fantastic.'}])
        patcher.start()
        self.addCleanup(patcher.stop)

    def where(self, inside):
        return patch.multiple(self.h, slot=Mock(return_value=Mock()),
                              _where=Mock(return_value=([0, 0, 0], 'ground', inside and {'id': inside, 'name': inside})))

    def test_names_ids_and_parts_of_names(self):
        for target in ('Dungeon045', '吉鲁塔古马奇神庙', '吉鲁塔古马奇', 'jirutagumac shrine'):
            got = self.h.guide(target)['target']
            self.assertEqual((got['id'], got['name'], got['name_en'], got['kind']),
                             ('Dungeon045', '吉鲁塔古马奇神庙', 'Jirutagumac Shrine', '神庙'), target)
        self.assertEqual(self.h.guide('迷路的小孩')['target']['name_en'], 'The Lost Child')
        self.assertEqual(self.h.guide('迷路的小孩')['target']['kind'], '任务')
        with self.assertRaisesRegex(harness.ToolError, '对得上好几个'):
            self.h.guide('神庙')
        with self.assertRaisesRegex(harness.ToolError, '没有叫'):
            self.h.guide('不存在')
        self.assertTrue(all(name in ('Jirutagumac Shrine', 'The Lost Child') for name in self.fetched))

    def test_current_from_live_state_then_save(self):
        live = {'position': [1010.0, 1500.0, -2030.0], 'nearby': []}
        with patch.object(self.h, '_live', return_value=harness.live_view(live)), self.where(None):
            got = self.h.guide('current')['target']
        self.assertEqual(got['id'], 'Dungeon045')
        self.assertIn('实时位置', got['chosen_by'])
        inside = harness.live_view({'position': [0.0, 16.6, 130.1], 'facing': [0, 0, -1],
                                    'nearby': [{'name': 'DgnObj_Small_Warpin_B_02', 'position': [0, 16, 120], 'distance': 10}]})
        with patch.object(self.h, '_live', return_value=inside), self.where('Dungeon045'):
            self.assertEqual(self.h.guide()['target']['id'], 'Dungeon045')
        with patch.object(self.h, '_live', return_value=inside), self.where(None):
            with self.assertRaisesRegex(harness.ToolError, '说出神庙名字'):
                self.h.guide()
        far = {'position': [3000.0, 200.0, 3000.0], 'nearby': []}
        with patch.object(self.h, '_live', return_value=harness.live_view(far)), self.where('Dungeon045'):
            self.assertIn('多半还在里面', self.h.guide()['target']['chosen_by'])   # a shrine's own coordinates
        with patch.object(self.h, '_live', return_value=harness.live_view(far)), self.where(None):
            with self.assertRaisesRegex(harness.ToolError, '没有神庙'):
                self.h.guide()
        title = {'position': [0.0, -0.15, 0.0], 'facing': [0, 0, 1], 'nearby': []}
        with patch.object(self.h, '_live', return_value=harness.live_view(title)), self.where('Dungeon045'):
            with self.assertRaisesRegex(harness.ToolError, '标题画面'):
                self.h.guide()
        with patch.object(self.h, '_live', return_value=None), self.where('Dungeon001'):
            got = self.h.guide()['target']
        self.assertEqual((got['id'], got['name_en']), ('Dungeon001', 'Ukouh Shrine'))
        self.assertIn('无法实时核对', got['chosen_by'])

    def test_the_games_own_names_for_what_a_guide_mentions(self):
        self.assertEqual(self.h.guide('Dungeon045')['names'],
                         {'Jirutagumac Shrine': '吉鲁塔古马奇神庙', 'Wing': '翼', 'Cart': '平台车', 'Recall': '倒转乾坤'})
        self.assertEqual([self.h.actor_name(a) for a in ('SpObj_LiftGeneratorWing_A_01', 'SpObj_Cart_B_02',
                                                          'Weapon_Sword_001', 'DgnObj_Small_Warpin_B_02')],
                         ['翼', '平台车', '旅人之剑', None])

    def test_no_pages_says_not_to_guess(self):
        with patch.object(guides, 'fetch', return_value=[]):
            out = self.h.guide('Dungeon045')
        self.assertEqual(out['sources'], [])
        self.assertIn('不要凭画面猜', out['note'])

    def test_offered_unless_turned_off(self):
        self.assertIn('guide', [s['name'] for s in self.h.tool_specs()])
        off = harness.Harness({'guides': {'enabled': False}})
        self.assertNotIn('guide', [s['name'] for s in off.tool_specs()])


class ClaudeCodeWebTests(unittest.TestCase):
    def command(self, settings):
        seen = {}

        def run(command, ctx, prompt, env, cwd, on_line):
            seen['command'] = command
            on_line(json.dumps({'type': 'result', 'result': '去左边。'}))
            return 0, '', ''
        backend = backends.ClaudeCode({'claude_code': settings})
        with tempfile.TemporaryDirectory() as folder, patch.object(backends, 'run_process', side_effect=run), \
             patch.object(backend, 'binary', return_value='/bin/claude'):
            ctx = backends.Context({})
            ctx.workdir = Path(folder)
            backend.run('system', 'prompt', ctx)
        c = seen['command']
        return c[c.index('--tools') + 1], c[c.index('--allowedTools') + 1].split(',')

    def test_web_tools_for_walkthroughs_unless_turned_off(self):
        builtin, allowed = self.command({})
        self.assertEqual(builtin, 'WebSearch,WebFetch')
        self.assertIn('WebSearch', allowed)
        self.assertIn('mcp__totk-harness__guide', allowed)
        builtin, allowed = self.command({'web': False})
        self.assertEqual(builtin, '')
        self.assertNotIn('WebFetch', allowed)


if __name__ == '__main__':
    unittest.main()
