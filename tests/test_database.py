import hashlib
import sqlite3
import zipfile
from threading import Event

import pytest
import pymupdf

from lotfinder.job import execute
from lotfinder.models import ScanConfig, Cancelled
from lotfinder.database import database_records
from lotfinder.scanner import Scanner
from lotfinder.store import Store


def make_db(path):
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE "设备日志" (id INTEGER PRIMARY KEY, machine TEXT, lot TEXT, state TEXT)')
        db.executemany('INSERT INTO "设备日志" VALUES (?,?,?,?)',
                       [(i, "机台", "AT0004.13 AT0004.13", "正常") for i in range(1, 9)])
        db.execute('CREATE TABLE other (value TEXT)')
        db.execute('INSERT INTO other VALUES (?)', ("AT0004.13",))
        db.execute('CREATE VIEW duplicate AS SELECT * FROM other')
    return path


def scan(tmp_path, path):
    store = Store(tmp_path / "result.sqlite3")
    Scanner(ScanConfig([path], tmp_path / "out"), store).run()
    return store


def test_all_tables_count_cap_neighbors_and_readonly(tmp_path):
    path = make_db(tmp_path / "日志.db3")
    digest = hashlib.sha256(path.read_bytes()).digest()
    store = scan(tmp_path, path)
    assert store.summary()["total"] == 17
    assert store.summary()["incomplete"] == 0
    evidence = store.evidence(1, "product_lot", "AT0004.13")
    assert len(evidence) == 5
    item = next(e for e in evidence if e["sheet"] == "设备日志")
    assert item["locator"] == "rowid=1"
    assert [c["header"] for c in item["cells"]] == ["machine", "lot", "state"]
    assert item["occurrences"] == 2
    assert hashlib.sha256(path.read_bytes()).digest() == digest
    assert not list(tmp_path.glob("日志.db3-*"))
    store.close()


@pytest.mark.parametrize("suffix", [".db3", ".db", ".sqlite", ".filepart"])
def test_database_inside_archive(tmp_path, suffix):
    db = make_db(tmp_path / ("data" + suffix))
    archive = tmp_path / "nested.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.write(db, "data" + suffix)
    store = scan(tmp_path, archive)
    assert store.summary()["total"] == 17
    assert store.summary()["incomplete"] == 0
    store.close()


def test_without_rowid_and_quoted_identifiers(tmp_path):
    path = tmp_path / "quoted.db3"
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE "table""x" ("key" TEXT PRIMARY KEY, "lot""id" TEXT) WITHOUT ROWID')
        db.execute('INSERT INTO "table""x" VALUES (?,?)', ("唯一值", "APE10264"))
    store = scan(tmp_path, path)
    evidence = store.evidence(1, "foup", "APE10264")[0]
    assert evidence["locator"] == "主键：key=唯一值"
    assert evidence["column"] == 'lot"id'
    store.close()


def test_blob_is_explicitly_incomplete(tmp_path):
    path = tmp_path / "binary.db3"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE data (text TEXT, binary BLOB)")
        db.execute("INSERT INTO data VALUES (?,?)", ("APE10264", b"APE10264"))
    store = scan(tmp_path, path)
    assert store.summary()["total"] == 1
    file = list(store.files())[0]
    assert file["status"] == "部分完成"
    assert "BLOB" in file["error"]
    store.close()


def test_invalid_db3_is_failure(tmp_path):
    path = tmp_path / "encrypted.db3"
    path.write_bytes(b"not sqlite: APE10264")
    store = scan(tmp_path, path)
    assert list(store.files())[0]["status"] == "失败"
    assert store.summary()["total"] == 0
    store.close()


@pytest.mark.parametrize("archived", [False, True])
def test_wal_not_silently_ignored(tmp_path, archived):
    path = make_db(tmp_path / "live.db3")
    db = sqlite3.connect(path)
    try:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("INSERT INTO other VALUES ('APE10264')")
        db.commit()
        source = path
        if archived:
            source = tmp_path / "wal.zip"
            with zipfile.ZipFile(source, "w") as z:
                z.write(path, path.name)
                z.write(str(path) + "-wal", path.name + "-wal")
        store = scan(tmp_path, source)
        assert store.summary()["incomplete"] > 0
        assert any("WAL" in r["error"] for r in store.files())
        store.close()
    finally:
        db.close()


def test_cancel_database_scan(tmp_path):
    path = make_db(tmp_path / "cancel.db3")
    cancelled = Event()
    def check():
        if cancelled.is_set():
            raise Cancelled()
    records = database_records(path, check, [])
    next(records)
    cancelled.set()
    with pytest.raises(Cancelled):
        list(records)


def test_database_pdf_has_real_locator(tmp_path):
    path = make_db(tmp_path / "report.db3")
    pdf, _, _ = execute(ScanConfig([path], tmp_path / "reports", include_match_details=True))
    with pymupdf.open(pdf) as doc:
        text = "".join(p.get_text() for p in doc)
    assert "数据表：设备日志" in text
    assert "rowid=1" in text
    assert "字段：lot" in text
