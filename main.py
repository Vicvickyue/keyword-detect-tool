"""Desktop entry point; CLI mode also works in the packaged Windows executable."""
import argparse
import json
import sys
from pathlib import Path


def main():
    if "--scan" not in sys.argv:
        from lotfinder.gui import main as gui_main
        return gui_main()
    from lotfinder.job import execute
    from lotfinder.models import ScanConfig
    parser = argparse.ArgumentParser(description="本地关键词检索及 PDF 报告")
    parser.add_argument("--scan", nargs="+", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--product", type=Path)
    parser.add_argument("--eqid", type=Path)
    parser.add_argument("--layer", type=Path)
    parser.add_argument("--ignore-case", action="store_true")
    parser.add_argument("--contains", action="store_true")
    parser.add_argument("--depth", type=int, default=10)
    args = parser.parse_args()
    config = ScanConfig(args.scan, args.output,
        dictionaries={k: v for k in ("product", "eqid", "layer") if (v := getattr(args, k))},
        case_sensitive=not args.ignore_case, whole_id=not args.contains, max_depth=args.depth)
    try:
        path, summary, state = execute(config)
        if sys.stdout:
            print(json.dumps({"pdf": str(path), "summary": summary, "state": state}, ensure_ascii=False))
        return 0 if state == "完成" and summary["incomplete"] == 0 else 2
    except Exception as exc:
        args.output.mkdir(parents=True, exist_ok=True)
        (args.output / "error.txt").write_text(f"{type(exc).__name__}: {exc}", encoding="utf-8")
        if sys.stderr:
            print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
