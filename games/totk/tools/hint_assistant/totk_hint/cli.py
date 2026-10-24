"""Command line of the stuck helper (卡关助手). From games/totk/tools/hint_assistant:

    python3.14 -m totk_hint hint --tier 1            a hint for the newest save (tiers: 1 where, 2 what, 3 how)
    python3.14 -m totk_hint serve                    the service the game's key 8 talks to
    python3.14 -m totk_hint mcp                      the totk-harness MCP server (stdio)
    python3.14 -m totk_hint state | quests | search <words> | backends | tables | config

(or `python3.14 run.py ...` from anywhere)."""
import argparse
import json
import sys

from . import backends as backendmod
from . import config as configmod


def _common(p):
    p.add_argument('--config', help='assistant.json to use (default: ~/Library/Application Support/MacNativeGames/TOTK/assistant.json)')
    p.add_argument('--romfs', help='game data folder (romfs.bin + runtime-index.bin or index.json)')
    p.add_argument('--save-root', help='folder with <user id>/slot_NN (default: the player\'s profile)')


def _print(value):
    print(json.dumps(value, ensure_ascii=False, indent=1))


def main(argv=None):
    parser = argparse.ArgumentParser(prog='totk_hint', description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('live', help='live runtime state or one bounded controller action')
    p.add_argument('op', choices=('state','press','stop','wait'))
    p.add_argument('--button')
    p.add_argument('--duration-ms',type=int,default=150)
    p.add_argument('--folder')
    p = sub.add_parser('hint', help='one hint for the current save')
    _common(p)
    p.add_argument('--tier', type=int, choices=(1, 2, 3), help='1 where to go, 2 what to use, 3 full solution (default: assistant.json)')
    p.add_argument('--backend', default='auto', choices=('auto',) + configmod.BACKENDS)
    p.add_argument('--question', help='what the player is stuck on, in their words')
    p.add_argument('--screenshot', action=argparse.BooleanOptionalAction, default=None,
                   help='let the model look at the game window (only while the game runs)')
    p.add_argument('--json', action='store_true', help='print the whole result as JSON')
    p.add_argument('--prompt-only', action='store_true', help='print the prompt instead of asking a model')
    p = sub.add_parser('serve', help='answer the game\'s key 8 requests (hint-request.json -> hint-response.json)')
    _common(p)
    p.add_argument('--accept-pending', action='store_true', help='handle a request written during service startup')
    p.add_argument('--parent-pid', type=int, help='stop when this process (the game) exits')
    p.add_argument('--log', help='append the service log to this file')
    p.add_argument('--folder', help='folder of hint-request.json / hint-response.json (default: the game\'s data folder)')
    p = sub.add_parser('mcp', help='the totk-harness MCP server on stdin/stdout')
    _common(p)
    p.add_argument('--allow-screenshot', action='store_true', help='offer the screenshot tool')
    p = sub.add_parser('state', help='print game_state')
    _common(p)
    p.add_argument('--slot', help='slot_00 ... slot_05 (default: the save being played)')
    p = sub.add_parser('quests', help='print quest_log')
    _common(p)
    p.add_argument('--query')
    p.add_argument('--all', action='store_true', help='also finished side quests')
    p = sub.add_parser('search', help='print search_text results')
    _common(p)
    p.add_argument('query', nargs='+')
    p.add_argument('--limit', type=int, default=10)
    p = sub.add_parser('backends', help='which model backends can run here')
    _common(p)
    p = sub.add_parser('tables', help='build (or rebuild) the cached tables from the game data')
    _common(p)
    p.add_argument('--rebuild', action='store_true')
    p = sub.add_parser('config', help='print the effective settings')
    _common(p)
    p.add_argument('--init', action='store_true', help='write assistant.json with the defaults (never overwrites)')
    args = parser.parse_args(argv)

    if args.command == 'live':
        from .live import call
        try:
            reply=call(args.op,args.button,args.duration_ms,args.folder);_print(reply);return 0 if reply['ok'] else 1
        except (ValueError,TimeoutError,OSError) as e:
            _print({'ok':False,'error':str(e)});return 1
    if args.command == 'config' and args.init:
        print(configmod.write_default(args.config))
        return 0
    try:
        config = configmod.load(args.config)
    except ValueError as e:
        print(e, file=sys.stderr)
        return 2
    args.config_data = config
    if args.command == 'mcp':
        from . import mcp_server
        return mcp_server.main(args)
    if args.command == 'serve':
        from . import service
        return service.serve(args)
    if args.command == 'config':
        _print(config)
        return 0
    if args.command == 'backends':
        for name, ok, why in backendmod.report(config):
            print(f'{name:20} {"ok" if ok else "unavailable"}{": " + why if why else ""}')
        return 0
    if args.command == 'tables':
        from . import tables
        t = tables.load(args.romfs, config, rebuild=args.rebuild)
        _print({'cache': str(t.folder), 'romfs': t.data.get('romfs'), 'quests': len(t.challenges),
                'places': len(t.locations), 'enum_values': len(t.enums), 'build_seconds': t.data.get('seconds')})
        return 0
    from .harness import Harness, ToolError
    harness = Harness(config, args.romfs, args.save_root)
    try:
        if args.command == 'state':
            _print(harness.game_state(args.slot))
        elif args.command == 'quests':
            _print(harness.quest_log(args.query, args.all, 40))
        elif args.command == 'search':
            _print(harness.search_text(' '.join(args.query), args.limit))
        elif args.command == 'hint':
            from . import service
            if args.prompt_only:
                from .harness import compact_snapshot
                from .prompts import SYSTEM, user_prompt
                tier = args.tier or config['tier_default']
                print(SYSTEM + '\n\n' + user_prompt(tier, compact_snapshot(harness), args.question, None, bool(args.screenshot)))
                return 0
            result = service.hint(config, args.tier, args.backend, args.question, None, args.screenshot, args.romfs,
                                  args.save_root)
            if args.json:
                _print(result)
            else:
                print(result['text'])
                print(f'\n[{result["tier"]} 档 · {result["backend"]} · {result["seconds"]} s]', file=sys.stderr)
    except ToolError as e:
        print(e, file=sys.stderr)
        return 1
    except backendmod.BackendError as e:
        print(e, file=sys.stderr)
        return 1
    return 0
