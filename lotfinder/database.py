"""Read closed, standalone SQLite databases without changing source files."""
import sqlite3
import tempfile
from pathlib import Path

from .readers import value_text


def quote(name):
    return '"' + name.replace('"', '""') + '"'


def check_sidecars(path):
    for suffix in ("-wal", "-journal"):
        sidecar = Path(str(path) + suffix)
        if sidecar.exists() and sidecar.stat().st_size:
            raise ValueError("数据库存在非空 WAL/事务日志。请关闭写入程序并导出完整的单文件 SQLite 数据库后重试。")


def database_records(path, check, warnings):
    check()
    with path.open("rb") as source:
        if source.read(16) != b"SQLite format 3\x00":
            raise ValueError("不是标准 SQLite 3 数据库，可能已加密、损坏或采用私有格式。")
    check_sidecars(path)
    before = path.stat()
    # Immutable applies only to our private copy, never to a potentially changing original.
    with tempfile.TemporaryDirectory(prefix="lotfinder-sqlite-") as directory:
        snapshot = Path(directory) / "snapshot.db3"
        with path.open("rb") as source, snapshot.open("wb") as target:
            while chunk := source.read(1024**2):
                check()
                target.write(chunk)
        after = path.stat()
        check_sidecars(path)
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise ValueError("复制期间数据库发生变化，请停止写入后重试。")
        db = sqlite3.connect(snapshot.as_uri() + "?mode=ro&immutable=1", uri=True, timeout=2)
        def progress():
            try:
                check()
                return 0
            except Exception:
                return 1
        db.set_progress_handler(progress, 1000)
        try:
            db.execute("PRAGMA query_only=ON")
            db.execute("PRAGMA trusted_schema=OFF")
            db.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, 8 * 1024**2)
            integrity = [row[0] for row in db.execute("PRAGMA quick_check")]
            if integrity != ["ok"]:
                raise ValueError("SQLite 完整性检查失败：" + "; ".join(integrity[:5]))
            tables = sorted(db.execute("PRAGMA main.table_list"), key=lambda row: row[1])
            blobs = 0
            for schema, name, kind, _, without_rowid, *_ in tables:
                check()
                if schema != "main" or name.startswith("sqlite_") or kind == "view":
                    continue
                if kind != "table":
                    warnings.append(f"未检索特殊表 {name}（{kind}）；仅支持普通数据表。")
                    continue
                try:
                    columns = [row for row in db.execute(f"PRAGMA main.table_xinfo({quote(name)})") if row[6] != 1]
                    headers = [row[1] for row in columns]
                    lowered = {h.lower() for h in headers}
                    rowid = next((alias for alias in ("rowid", "_rowid_", "oid") if alias not in lowered), None)
                    if without_rowid:
                        rowid = None
                    keys = [row[1] for row in sorted(columns, key=lambda row: row[5]) if row[5]]
                    order = [rowid] if rowid else keys
                    projection = ([quote(rowid)] if rowid else []) + [quote(h) for h in headers]
                    statement = "SELECT " + ",".join(projection) + " FROM main." + quote(name)
                    if order:
                        statement += " ORDER BY " + ",".join(quote(h) for h in order)
                    for number, data in enumerate(db.execute(statement), 1):
                        check()
                        values = data[1:] if rowid else data
                        if rowid:
                            locator = f"rowid={data[0]}"
                        elif keys:
                            locator = "主键：" + ", ".join(f"{k}={value_text(values[headers.index(k)])}" for k in keys)
                        else:
                            locator = f"扫描记录序号={number}（无可用 rowid/主键）"
                        texts = []
                        for value in values:
                            if isinstance(value, bytes):
                                blobs += 1
                                texts.append(f"[BLOB 二进制内容，{len(value)} 字节，未检索]")
                            else:
                                texts.append(value_text(value))
                        for col, text in enumerate(texts):
                            if not text or isinstance(values[col], bytes):
                                continue
                            cells = [{"column": headers[i], "header": headers[i], "value": texts[i],
                                      "matched": i == col}
                                     for i in range(max(0, col - 1), min(len(headers), col + 2))]
                            yield text, {"type": "database", "sheet": name, "row": number,
                                         "column": headers[col], "locator": locator, "cells": cells}
                except sqlite3.Error as exc:
                    check()
                    warnings.append(f"未检索完整的数据表 {name}：{exc}")
            if blobs:
                warnings.append(f"未检索 {blobs} 个 BLOB 二进制字段；文本与数值字段已扫描。")
        except sqlite3.Error:
            check()
            raise
        finally:
            db.close()
