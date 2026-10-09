import tempfile
from pathlib import Path

from .report import export_report
from .scanner import Scanner
from .store import Store


def execute(config, cancel=None, progress=None):
    config.validate()
    config.output.mkdir(parents=True, exist_ok=True)
    if any(p.resolve() == config.output.resolve() for p in config.sources):
        raise ValueError("报告输出目录不能与待检索目录相同，请选择单独的输出目录。")
    with tempfile.TemporaryDirectory(prefix="lotfinder-results-") as directory:
        store = Store(Path(directory) / "results.sqlite3")
        try:
            Scanner(config, store, cancel, progress).run()
            if progress:
                progress(dict(store.summary(), current="正在排版并生成 PDF，请稍候……"))
            path = export_report(store, config.output)
            return path, store.summary(), store.metadata()["state"]
        finally:
            store.close()
