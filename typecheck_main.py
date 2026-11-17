import argparse
import json
import sys
from pathlib import Path


def main():
    if '--scan' not in sys.argv:
        from typecheck.gui import main as gui
        return gui()
    from typecheck import TYPES
    from typecheck.engine import Config, execute
    parser = argparse.ArgumentParser(description='文件类型检查：按后缀，不验证内容格式')
    parser.add_argument('--scan', nargs='+', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--types', nargs='+', choices=list(TYPES), default=list(TYPES))
    parser.add_argument('--no-archives', action='store_true')
    parser.add_argument('--depth', type=int, default=10)
    parser.add_argument('--full-list', action='store_true')
    args = parser.parse_args()
    try:
        pdf, result = execute(Config(args.scan, args.output, set(args.types), not args.no_archives, args.full_list, args.depth))
        if sys.stdout: print(json.dumps(dict(pdf=str(pdf), state=result['state'], matched=result['matched']), ensure_ascii=False))
        return 0 if result['state'] == '完成' else 2
    except Exception as exc:
        args.output.mkdir(parents=True, exist_ok=True)
        (args.output / 'error.txt').write_text(str(exc), encoding='utf-8')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
