import json
from datetime import datetime
from pathlib import Path

import fitz
import pytest

from lotfinder.job import execute
from lotfinder.models import ScanConfig
from lotfinder.report import reserve_report
from lotfinder.report import write_pdf, PDFWriter
from lotfinder.scanner import Scanner
from lotfinder.store import Store
import zipfile


def pdf_text(path):
    with fitz.open(path) as doc:
        return "".join(page.get_text() for page in doc), len(doc)


def test_sequence_and_no_overwrite(tmp_path):
    date = datetime(2026, 10, 9)
    with reserve_report(tmp_path, date) as first:
        assert first.name == "检索报告_20261009_01.pdf"
        first.write_bytes(b"existing")
        with reserve_report(tmp_path, date) as second:
            assert second.name == "检索报告_20261009_02.pdf"
    assert first.read_bytes() == b"existing"
    (tmp_path / "检索报告_20261009_99.pdf").touch()
    with pytest.raises(ValueError, match="用完"):
        with reserve_report(tmp_path, date):
            pass


def test_pdf_chinese_long_evidence_and_log(tmp_path):
    source = tmp_path / "日志.txt"
    source.write_text("中文日志 AT0004.13 <>&\n" + "超长内容" * 1500 + " APE10264 尾部标记", encoding="utf-8")
    pdf, summary, state = execute(ScanConfig([source], tmp_path / "reports", include_match_details=True))
    assert summary["total"] == 2
    assert state == "完成"
    with fitz.open(pdf) as doc:
        text = "".join(page.get_text() for page in doc)
        assert "文件关键词检索报告" in text
        assert "AT0004.13" in text
        assert "尾部标记" in text
        assert len(doc) >= 3
        # A real TrueType font is embedded rather than relying on the reader's CJK font pack.
        assert any("ReportChinese" in font[4] or "Microsoft" in font[3] or "YaHei" in font[3]
                   for font in doc[0].get_fonts())
    entries = [json.loads(line) for line in pdf.with_suffix(".jsonl").read_text(encoding="utf-8").splitlines()]
    assert len([e for e in entries if e["type"] == "hit"]) == 2
    assert not list((tmp_path / "reports").glob("*.lock"))


def test_details_optional_and_complete_table_and_log(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    for index in range(80):
        (source / f"unmatched-{index:03d}.txt").write_text("nothing here")
    (source / "matched.log").write_text("APE10264 evidence-marker\n" * 9)
    compact, summary, _ = execute(ScanConfig([source], tmp_path / "compact"))
    full, full_summary, _ = execute(ScanConfig([source], tmp_path / "full", include_match_details=True))
    compact_text, compact_pages = pdf_text(compact)
    full_text, full_pages = pdf_text(full)
    assert summary == full_summary
    assert "unmatched-079.txt" in compact_text
    assert "unmatched-079.txt" in full_text
    assert "附录 / 完整文件清单" not in compact_text
    assert "03 / 匹配明细" in full_text
    assert "03 / 匹配明细" not in compact_text
    assert "evidence-marker" not in compact_text
    assert "evidence-marker" in full_text
    assert "无匹配文件 80" in compact_text
    assert full_pages >= compact_pages
    logs = []
    for pdf in (compact, full):
        records = [json.loads(line) for line in pdf.with_suffix(".jsonl").read_text(encoding="utf-8").splitlines()]
        logs.append([r for r in records if r["type"] != "task"])
        assert len([r for r in records if r["type"] == "file"]) == 81
    assert logs[0] == logs[1]


def test_compact_keeps_archive_errors_and_partial_matches(tmp_path):
    path = tmp_path / "input"
    path.mkdir()
    (path / "bad.zip").write_bytes(b"PK\x03\x04broken")
    (path / "ok.log").write_text("APE10264")
    store = Store(tmp_path / "result.sqlite3")
    Scanner(ScanConfig([path], tmp_path / "out"), store).run()
    matched = next(r for r in store.files() if r["total"])
    store.finish(matched["id"], "部分完成", "测试：后续内容未检索")
    pdf = tmp_path / "partial.pdf"
    write_pdf(store, pdf)
    text, _ = pdf_text(pdf)
    assert "bad.zip" in text and "部分完成" in text
    assert "测试：后续内容未检索" in text
    assert "已完整扫描内容文件 0" in text
    assert "无匹配文件 0" in text
    assert "异常条目 2" in text
    assert "已观察" in text and "NA" in text
    assert "04 / 异常文件" not in text
    store.close()


def test_no_hits_and_container_summary(tmp_path):
    source = tmp_path / "normal.zip"
    with zipfile.ZipFile(source, "w") as z:
        z.writestr("hidden-clean.txt", "nothing")
    pdf, _, _ = execute(ScanConfig([source], tmp_path / "out"))
    text, pages = pdf_text(pdf)
    assert "hidden-clean.txt" in text
    assert "已完整扫描内容文件 1" in text
    assert "压缩容器 1，已展开 1" in text
    assert "无" in text and "不适用" in text
    assert pages <= 2


def test_table_paginates_long_paths_without_losing_tail(tmp_path):
    pdf = tmp_path / "long.pdf"
    writer = PDFWriter(pdf)
    rows = [[("路径/" * 1800 + "尾部标记") if i == 1 else f"source-{i}",
             f"data-{i}.log", ".log / text", "完成", "APE10264", "1"]
            for i in range(1, 75)]
    writer.result_table(rows)
    writer.save()
    text, pages = pdf_text(pdf)
    assert "尾部标记" in text and "data-74.log" in text
    assert pages > 2
    assert text.count("文档路径") >= pages


def test_completed_format_notes_hidden_in_pdf(tmp_path):
    path = tmp_path / "clean.txt"
    path.write_text("nothing")
    store = Store(tmp_path / "result.sqlite3")
    Scanner(ScanConfig([path], tmp_path / "out"), store).run()
    note = "公式缓存未逐项验证。"
    store.finish(1, "完成", note)
    second = store.add_file("second.xls", "second.xls", ".xls", "xls", 0)
    store.finish(second, "完成", note)
    pdf = tmp_path / "grouped.pdf"
    write_pdf(store, pdf)
    text, _ = pdf_text(pdf)
    assert note not in text
    assert "second.xls" in text
    store.close()


def test_unified_table_columns_and_keyword_counts(tmp_path):
    from lotfinder.report import result_rows
    source = tmp_path / "counts.txt"
    source.write_text("APE10264 APE10264 AT0004.13 AT0004.14")
    store = Store(tmp_path / "counts.sqlite3")
    Scanner(ScanConfig([source], tmp_path / "out"), store).run()
    rows = list(result_rows(store))
    assert len(rows) == 3
    assert sorted(row[-1] for row in rows) == ["1", "1", "2"]
    assert all(len(row) == 6 and row[0] == str(source.parent) and row[1] == source.name for row in rows)
    pdf = tmp_path / "counts.pdf"
    write_pdf(store, pdf)
    text, _ = pdf_text(pdf)
    for label in ["文档路径", "文档名", "文档类型", "解析情况", "关键词", "匹配次数"]:
        assert label in text
    store.close()


def test_paths_merge_per_page_and_repeat_on_continuation(tmp_path):
    pdf = tmp_path / "merged.pdf"
    writer = PDFWriter(pdf)
    rows = [["shared-directory", f"file-{i:03d}.txt", ".txt", "完成", "无", "0"] for i in range(90)]
    rows += [["other-directory", "other.txt", ".txt", "失败", "NA", "—"],
             ["shared-directory", "last.txt", ".txt", "完成", "无", "0"]]
    writer.result_table(rows)
    writer.save()
    with fitz.open(pdf) as doc:
        assert len(doc) > 1
        for page in list(doc)[:-1]:
            assert page.get_text().count("shared-directory") == 1
        text = "".join(page.get_text() for page in doc)
        assert text.count("shared-directory") == len(doc) + 1
        for i in range(90):
            assert text.count(f"file-{i:03d}.txt") == 1
        assert "other.txt" in text and "last.txt" in text
