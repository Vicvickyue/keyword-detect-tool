import json
from datetime import datetime
from pathlib import Path

import fitz
import pytest

from lotfinder.job import execute
from lotfinder.models import ScanConfig
from lotfinder.report import reserve_report


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
    pdf, summary, state = execute(ScanConfig([source], tmp_path / "reports"))
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
