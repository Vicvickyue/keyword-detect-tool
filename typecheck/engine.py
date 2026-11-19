import os
import re
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path, PureWindowsPath
from threading import Event

from .archives import ArchiveReader
from lotfinder.models import Cancelled, LimitExceeded
from . import TYPES, VERSION

ARCHIVES = {'.zip', '.7z', '.rar', '.tar', '.gz', '.tgz', '.bz2', '.xz', '.001', '.filepart'}


@dataclass
class Config:
    sources: list[Path]
    output: Path
    selected: set[str] = field(default_factory=lambda: set(TYPES))
    archives: bool = True
    full_list: bool = False
    max_depth: int = 10
    max_files: int = 10000
    max_file_bytes: int = 2 * 1024**3
    max_expanded_bytes: int = 10 * 1024**3
    archive_timeout: int = 180
    seven_zip: str = ''

    def validate(self):
        self.sources = [Path(p).absolute() for p in self.sources]
        self.output = Path(self.output).resolve()
        self.selected = {s.lower() for s in self.selected}
        if not self.sources or any(not p.exists() for p in self.sources):
            raise ValueError('请选择存在的文件或文件夹。')
        if not self.selected or self.selected - TYPES.keys():
            raise ValueError('请至少勾选一个支持的后缀。')
        if any(p.resolve() == self.output or self.output in p.resolve().parents for p in self.sources):
            raise ValueError('输出目录不能与输入目录相同，也不能是输入文件或目录的上级目录。')
        if not 5 <= self.max_depth <= 30 or min(self.max_files, self.max_file_bytes, self.max_expanded_bytes, self.archive_timeout) <= 0:
            raise ValueError('压缩深度需为 5～30，资源限制必须为正数。')


class Scanner:
    def __init__(self, config, cancel=None, progress=None):
        self.config = config
        self.cancel = cancel or Event()
        self.progress = progress or (lambda data: None)
        self.rows = []
        self.seen = set()
        self.reader = ArchiveReader(config, self.check)

    def check(self):
        if self.cancel.is_set():
            raise Cancelled('用户取消，剩余内容未检查。')

    def add(self, source, name, directory, depth, status='已检查', reason='', is_file=True):
        self.check()
        if len(self.rows) >= self.config.max_files:
            raise LimitExceeded('已达到扫描条目上限，剩余内容未检查。')
        suffix = PureWindowsPath(name).suffix.lower()
        row = dict(source=source, directory=directory, name=PureWindowsPath(name).name,
                   suffix=suffix, matched=is_file and suffix in self.config.selected,
                   status=status, reason=str(reason), depth=depth)
        self.rows.append(row)
        self.progress(dict(files=len(self.rows), matched=sum(r['matched'] for r in self.rows), current=source))
        return row

    def run(self):
        self.config.validate()
        started = datetime.now().isoformat(timespec='seconds')
        state = '完成'
        try:
            for source in self.config.sources:
                self.walk(source)
        except Cancelled:
            state = '已取消，未完整扫描'
        except LimitExceeded as exc:
            state = '受限，未完整扫描：' + str(exc)
        issues = sum(bool(r['reason']) for r in self.rows)
        if state == '完成' and issues:
            state = '存在未完成项'
        return dict(version=VERSION, started=started, finished=datetime.now().isoformat(timespec='seconds'),
                    state=state, sources=[str(p) for p in self.config.sources],
                    selected=sorted(self.config.selected), archives=self.config.archives,
                    max_depth=self.config.max_depth, scope='按最终后缀匹配，不区分大小写；不验证内容格式',
                    counts={s: sum(r['matched'] and r['suffix'] == s for r in self.rows) for s in sorted(self.config.selected)},
                    files=len(self.rows), matched=sum(r['matched'] for r in self.rows), issues=issues, rows=self.rows)

    def walk(self, path):
        self.check()
        # Check links before resolve; never traverse junctions or symlinked folders.
        if path.is_symlink() or (hasattr(path, 'is_junction') and path.is_junction()):
            self.add(str(path), path.name, str(path.parent), 0, '跳过', '不跟随链接或目录联接。', False)
            return
        resolved = path.resolve()
        if resolved == self.config.output or self.config.output in resolved.parents:
            return
        key = os.path.normcase(str(resolved))
        if key in self.seen:
            return
        self.seen.add(key)
        try:
            if path.is_dir():
                for child in sorted(path.iterdir(), key=lambda p: p.name.casefold()):
                    self.walk(child)
            elif path.is_file():
                row = self.add(str(path), path.name, str(path.parent), 0)
                part = re.search(r'\.part(\d+)\.rar$', path.name, re.I)
                volume = re.search(r'\.(\d{3}|z\d{2}|r\d{2})$', path.name, re.I)
                if self.config.archives and ((part and int(part[1]) > 1) or (volume and volume[1] != '001')):
                    if part:
                        first = path.with_name(path.name[:part.start(1)] + '1'.zfill(len(part[1])) + path.name[part.end(1):])
                    else:
                        first = path.with_suffix('.001' if volume[1].isdigit() else '.zip' if volume[1].lower().startswith('z') else '.rar')
                    row.update(status='分卷附件' if first.exists() else '未完成',
                               reason='' if first.exists() else '未找到首卷，请收齐分卷后扫描整个目录。')
                    if first.exists(): self.walk(first)
                    return
                if self.config.archives and path.suffix.lower() in ARCHIVES:
                    self.archive(path, row, 0)
            else:
                self.add(str(path), path.name, str(path.parent), 0, '跳过', '不是普通文件或文件已消失。', False)
        except (Cancelled, LimitExceeded):
            raise
        except OSError as exc:
            self.add(str(path), path.name, str(path.parent), 0, '失败', exc, False)

    def archive(self, path, row, depth):
        if depth >= self.config.max_depth:
            row.update(status='受限', reason='达到最大压缩层数，未检查内部文件。')
            return
        row['status'] = '正在展开'
        try:
            with tempfile.TemporaryDirectory(prefix='typecheck-') as temp:
                members = self.reader.members(path, Path(temp))
                for index, (name, size, problem) in enumerate(members):
                    self.check()
                    parent = str(PureWindowsPath(name).parent)
                    directory = row['source'] + ' → ' + ('（压缩包根目录）' if parent == '.' else parent)
                    child = self.add(row['source'] + ' → ' + name, name, directory, depth + 1,
                                     '已检查名称', is_file='链接' not in problem)
                    if problem:
                        child.update(status='名称已列出，内部未验证', reason=problem)
                        continue
                    if re.search(r'\.(?:\d{3}|z\d{2}|r\d{2}|part\d+\.rar)$', name, re.I):
                        child.update(status='未完成', reason='嵌套分卷不自动重组，请解包到同一目录后重扫。')
                        continue
                    if PureWindowsPath(name).suffix.lower() not in ARCHIVES:
                        continue
                    if depth + 1 >= self.config.max_depth:
                        child.update(status='受限', reason='达到最大压缩层数，未检查内部文件。')
                        continue
                    if size > self.config.max_file_bytes:
                        child.update(status='受限', reason='嵌套压缩文件超过解包大小限制。')
                        continue
                    target = Path(temp) / (f'member-{index}' + ''.join(PureWindowsPath(name).suffixes))
                    try:
                        self.reader.extract(path, name, target)
                        if size >= 0 and target.stat().st_size != size:
                            raise ValueError('实际解包长度与归档记录不符。')
                        self.archive(target, child, depth + 1)
                    except (Cancelled, LimitExceeded) as exc:
                        child.update(status='未完成', reason=str(exc))
                        raise
                    except Exception as exc:
                        child.update(status='失败', reason=str(exc))
                    finally:
                        target.unlink(missing_ok=True)
                row['status'] = '已列出内部文件'
        except Cancelled:
            row.update(status='已取消', reason='内部文件未全部检查。')
            raise
        except LimitExceeded as exc:
            row.update(status='受限', reason=str(exc))
            raise
        except Exception as exc:
            row.update(status='部分检查', reason=str(exc))


def execute(config, cancel=None, progress=None):
    from .reports import export
    result = Scanner(config, cancel, progress).run()
    pdf = export(result, config.output, config.full_list)
    return pdf, result
