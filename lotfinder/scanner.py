import os
import re
import tempfile
from datetime import datetime
from pathlib import Path
from threading import Event

from . import __version__
from .archives import ArchiveReader
from .database import database_records
from .models import Cancelled, LimitExceeded
from .readers import detect, text_records, csv_records, excel_records, check_workbook_zip
from .rules import Matcher


class Scanner:
    def __init__(self, config, store, cancel=None, progress=None):
        self.config = config
        self.store = store
        self.cancel = cancel or Event()
        self.progress = progress or (lambda data: None)
        self.reader = ArchiveReader(config, self.check)
        self.count = 0
        self.seen = set()
        self.matcher = None

    def check(self):
        if self.cancel.is_set():
            raise Cancelled("用户取消，扫描未完成。")

    def error_entry(self, source, name, depth, status, error):
        ident = self.store.add_file(source, name, Path(name).suffix, "未识别", depth)
        self.store.finish(ident, status, str(error))

    def run(self):
        self.config.validate()
        self.matcher = Matcher(self.config)
        self.store.meta("started", datetime.now().isoformat(timespec="seconds"))
        self.store.meta("version", __version__)
        self.store.meta("sources", [str(p.resolve()) for p in self.config.sources])
        self.store.meta("rules", self.matcher.active)
        self.store.meta("dictionaries", self.matcher.dictionary_info)
        self.store.meta("warnings", self.matcher.warnings)
        self.store.meta("settings", {"case_sensitive": self.config.case_sensitive,
            "whole_id": self.config.whole_id, "header_row": self.config.header_row,
            "max_depth": self.config.max_depth, "max_file_bytes": self.config.max_file_bytes,
            "max_expanded_bytes": self.config.max_expanded_bytes, "max_files": self.config.max_files,
            "include_match_details": self.config.include_match_details})
        state = "完成"
        try:
            for source in self.config.sources:
                self.check()
                self.walk(source.resolve())
        except Cancelled:
            state = "已取消（未完整扫描）"
        except LimitExceeded as exc:
            state = f"达到任务限制（未完整扫描）：{exc}"
        except Exception as exc:
            state = f"任务异常（未完整扫描）：{type(exc).__name__}: {exc}"
        summary = self.store.summary()
        if state == "完成" and summary["incomplete"]:
            state = "结束（存在未完整扫描的文件）"
        self.store.meta("state", state)
        self.store.meta("finished", datetime.now().isoformat(timespec="seconds"))
        self.store.meta("expanded_bytes", self.reader.expanded)
        self.progress(dict(summary, current=state))
        return state

    def walk(self, source):
        self.check()
        if source.is_symlink() or (hasattr(source, "is_junction") and source.is_junction()):
            self.error_entry(str(source), source.name, 0, "跳过", "不跟随文件系统链接或目录联接。")
            return
        if source.is_dir():
            if source == self.config.output.resolve():
                return
            try:
                entries = sorted(source.iterdir(), key=lambda p: p.name.casefold())
            except OSError as exc:
                self.error_entry(str(source), source.name, 0, "失败", exc)
                return
            for path in entries:
                self.walk(path)
        else:
            key = str(source.resolve()).casefold()
            if key in self.seen:
                return
            self.seen.add(key)
            if source in {p.resolve() for p in self.config.dictionaries.values()}:
                return
            part = re.search(r"\.part([0-9]+)\.rar$", source.name, re.I)
            if part and int(part.group(1)) > 1:
                digits = part.group(1)
                first_name = source.name[:part.start(1)] + "1".zfill(len(digits)) + source.name[part.end(1):]
                first = source.with_name(first_name)
                self.error_entry(str(source), source.name, 0, "分卷附件" if first.exists() else "失败",
                                 "由首卷统一读取。" if first.exists() else "未找到首卷，请收齐分卷。")
                return
            # Companion volumes are consumed by 7-Zip with their first volume, not scanned twice.
            if re.search(r"\.(?:00[2-9]|0[1-9][0-9]|[1-9][0-9]{2}|z[0-9]{2}|r[0-9]{2})$", source.name, re.I):
                first = source.with_suffix(".001") if source.suffix[1:].isdigit() else source.with_suffix(
                    ".zip" if source.suffix.lower().startswith(".z") else ".rar")
                self.error_entry(str(source), source.name, 0, "分卷附件" if first.exists() else "失败",
                                 "由首卷统一读取。" if first.exists() else "未找到首卷，请收齐分卷。")
                return
            self.visit(source, str(source), source.name, 0)

    def visit(self, path, source, name, depth):
        self.check()
        if self.count >= self.config.max_files:
            self.error_entry(source, name, depth, "跳过", "达到任务文件数上限，其余文件未扫描。")
            raise LimitExceeded("文件数上限")
        self.count += 1
        ident = self.store.add_file(source, name, Path(name).suffix, "未识别", depth)
        self.progress(dict(self.store.summary(), current=source))
        try:
            if path.stat().st_size > self.config.max_file_bytes:
                raise LimitExceeded("单文件大小超过配置限制。")
            kind = detect(path, name)
            self.store.db.execute("UPDATE files SET kind=? WHERE id=?", (kind, ident))
            if kind == "archive":
                if depth >= self.config.max_depth:
                    raise LimitExceeded(f"达到 {self.config.max_depth} 层压缩深度限制。")
                self.archive(path, source, depth)
                self.store.finish(ident, "已展开")
                return
            if kind == "unsupported":
                self.store.finish(ident, "不支持", "无法识别的二进制格式。")
                return
            warnings = []
            if kind == "csv":
                records = csv_records(path, name, self.config.header_row, self.check)
            elif kind == "sqlite":
                records = database_records(path, self.check, warnings)
            elif kind in {"xlsx", "xlsm", "xls", "xlsb", "ods"}:
                check_workbook_zip(path, self.config.max_expanded_bytes, self.config.max_files)
                records = excel_records(path, kind, self.config.header_row, self.check, warnings)
            else:
                records = text_records(path, self.check)
            for text, payload in records:
                self.check()
                matches = self.matcher.matches(text)
                if matches:
                    self.store.record(ident, matches, payload)
            # XLS/ODS cache caveat is informational, XLSX missing caches are incomplete.
            incomplete = any("无缓存" in note or "未检索" in note for note in warnings)
            self.store.finish(ident, "部分完成" if incomplete else "完成", "\n".join(warnings))
        except Cancelled as exc:
            self.store.finish(ident, "已取消", str(exc))
            raise
        except LimitExceeded as exc:
            self.store.finish(ident, "受限", str(exc))
            if self.count >= self.config.max_files:
                raise
        except Exception as exc:
            self.store.finish(ident, "失败", f"{type(exc).__name__}: {exc}")

    def archive(self, path, source, depth):
        with tempfile.TemporaryDirectory(prefix="lotfinder-") as directory:
            temp = Path(directory)
            members = self.reader.members(path, temp)
            nonempty_members = {n for n, size, _ in members if size > 0}
            for index, (name, size, problem) in enumerate(members):
                self.check()
                child_source = f"{source} → {name}"
                if problem or size > self.config.max_file_bytes:
                    self.error_entry(child_source, name, depth + 1, "跳过", problem or "成员大小超过限制。")
                    continue
                # A generated name makes archive traversal / absolute paths harmless.
                suffix = Path(name).suffix
                suffix = suffix if re.fullmatch(r"\.[A-Za-z0-9]{1,12}", suffix) else ".bin"
                target = temp / f"member-{index}{suffix}"
                try:
                    self.reader.extract(path, name, target)
                    if size >= 0 and target.stat().st_size != size:
                        raise ValueError("实际解压长度与归档记录不符，内容可能不完整。")
                except Cancelled:
                    raise
                except Exception as exc:
                    self.error_entry(child_source, name, depth + 1, "失败", exc)
                    continue
                try:
                    if detect(target, name) == "sqlite" and any(
                            name + suffix in nonempty_members for suffix in ("-wal", "-journal")):
                        self.error_entry(child_source, name, depth + 1, "跳过",
                                         "压缩包内数据库带有 WAL/事务日志，请先导出完整的单文件 SQLite 数据库。")
                        continue
                    self.visit(target, child_source, name, depth + 1)
                finally:
                    target.unlink(missing_ok=True)
