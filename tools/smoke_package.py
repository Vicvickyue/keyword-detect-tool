"""End-to-end verification of the actual frozen EXE using bundled synthetic data."""
import argparse
import json
import os
import subprocess
import time
import pymupdf
from pathlib import Path


def run(package, output):
    executable = package / "KeywordReportTool.exe"
    sources = package / "示例/待检索文件"
    library = package / "示例/示例词库"
    env = dict(os.environ)
    # Do not depend on Python / Qt / conda / 7-Zip being on PATH.
    env["PATH"] = str(Path(os.environ.get("WINDIR", "C:/Windows")) / "System32")
    for key in ("PYTHONHOME", "PYTHONPATH", "QT_PLUGIN_PATH", "QT_QPA_PLATFORM_PLUGIN_PATH"):
        env.pop(key, None)
    result = subprocess.run([str(executable), "--scan", str(sources), "--output", str(output),
        "--product", str(library / "Product_ID.xlsx"), "--eqid", str(library / "EQID.xlsx"),
        "--layer", str(library / "Layer_Step.xlsx")], env=env, timeout=90)
    if result.returncode:
        raise RuntimeError(f"Packaged CLI failed: {result.returncode}")
    report = sorted(output.glob("*.pdf"))[-1]
    records = [json.loads(line) for line in report.with_suffix(".jsonl").read_text(encoding="utf-8").splitlines()]
    assert records[0]["summary"] == {"files": 12, "total": 41, "matched": 6, "incomplete": 0, "archives": 5}
    assert any(r["type"] == "file" and r["kind"] == "sqlite" and r["total"] == 6 for r in records)
    assert records[0]["settings"]["include_match_details"] is False
    with pymupdf.open(report) as document:
        compact_text = "".join(page.get_text() for page in document)
    assert "附录 / 完整文件清单" not in compact_text
    assert "无匹配.txt" in compact_text
    assert "03 / 匹配明细" not in compact_text
    full_output = output / "with-details"
    full_result = subprocess.run([str(executable), "--scan", str(sources), "--output", str(full_output),
        "--product", str(library / "Product_ID.xlsx"), "--eqid", str(library / "EQID.xlsx"),
        "--layer", str(library / "Layer_Step.xlsx"), "--match-details"], env=env, timeout=90)
    assert full_result.returncode == 0
    full_pdf = sorted(full_output.glob("*.pdf"))[-1]
    full_records = [json.loads(line) for line in full_pdf.with_suffix(".jsonl").read_text(encoding="utf-8").splitlines()]
    assert full_records[0]["settings"]["include_match_details"] is True
    assert records[1:] == full_records[1:]
    with pymupdf.open(full_pdf) as document:
        full_text = "".join(page.get_text() for page in document)
    assert "03 / 匹配明细" in full_text and "无匹配.txt" in full_text
    assert "rowid=" in full_text
    gui_env = dict(env, QT_QPA_PLATFORM="offscreen")
    process = subprocess.Popen([str(executable)], env=gui_env)
    try:
        time.sleep(3)
        assert process.poll() is None, "Packaged GUI failed during startup"
    finally:
        if process.poll() is None:
            process.terminate()
        process.wait(timeout=10)
    print("Packaged summary/details CLI and GUI startup passed; total matches: 41 (SQLite: 6)")
    print(report)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("package", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    run(args.package.resolve(), args.output.resolve())
