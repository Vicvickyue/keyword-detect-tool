"""Native ZIP/TAR reading for suffix checks; 7-Zip handles other formats."""
import stat
import tarfile
import time
import zipfile

from lotfinder.archives import ArchiveReader as SevenZipReader
from lotfinder.models import LimitExceeded


class CheckedInput:
    def __init__(self, source, check):
        self.source = source
        self.check = check

    def read(self, size=-1):
        self.check()
        return self.source.read(size)


class ArchiveReader(SevenZipReader):
    def kind(self, path):
        if path.suffix.lower() == '.001':
            return '7z'
        with path.open('rb') as source:
            header = source.read(512)
        if header[:4] in (b'PK\x03\x04', b'PK\x05\x06'):
            return 'zip'
        if path.suffix.lower() in {'.tar', '.tgz'} or path.name.lower().endswith('.tar.gz'):
            return 'tar'
        if len(header) == 512:
            try:
                tarfile.TarInfo.frombuf(header, 'utf-8', 'surrogateescape')
                return 'tar'
            except tarfile.HeaderError:
                pass
        return '7z'

    def guard(self, start):
        self.check()
        if time.monotonic() - start > self.config.archive_timeout:
            raise LimitExceeded('压缩包操作超时，未完整扫描。')

    def tar_members(self, archive, start):
        for info in archive:
            self.guard(start)
            # Stream mode avoids loading the archive into memory. Bound the
            # decompression work even when only member names are requested.
            if info.offset_data + info.size > self.config.max_expanded_bytes:
                raise LimitExceeded('TAR 展开读取超过体积限制，未完整扫描。')
            yield info

    def members(self, path, temp_dir):
        kind = self.kind(path)
        if kind == '7z':
            yield from super().members(path, temp_dir)
            return
        start = time.monotonic()
        seen = set()

        def record(name, size, problem):
            self.guard(start)
            if name in seen:
                raise ValueError('压缩包有重复成员路径，无法可靠逐文件计数。')
            seen.add(name)
            if len(seen) > self.config.max_files:
                raise LimitExceeded('压缩包成员数超过任务限制。')
            return name, size, problem

        if kind == 'zip':
            with zipfile.ZipFile(path) as archive:
                for info in archive.infolist():
                    if info.is_dir():
                        continue
                    problem = ''
                    if stat.S_ISLNK(info.external_attr >> 16):
                        problem = '压缩包中的链接不跟随。'
                    elif info.flag_bits & 1:
                        problem = '压缩成员已加密，未提供密码。'
                    yield record(info.filename, info.file_size, problem)
        else:
            try:
                with path.open('rb') as raw, tarfile.open(
                    fileobj=CheckedInput(raw, lambda: self.guard(start)), mode='r|*'
                ) as archive:
                    for info in self.tar_members(archive, start):
                        if info.isdir():
                            continue
                        problem = '' if info.isfile() else '压缩包中的链接或特殊成员不跟随。'
                        yield record(info.name, info.size, problem)
            except (tarfile.TarError, EOFError) as exc:
                raise ValueError(f'TAR 读取不完整（文件末端异常或归档结构错误）：{exc}') from exc

    def extract(self, path, member, target):
        kind = self.kind(path)
        if kind == '7z':
            return super().extract(path, member, target)
        start = time.monotonic()
        limit = min(self.config.max_file_bytes, self.config.max_expanded_bytes - self.expanded)

        def copy(source):
            written = 0
            with source, target.open('wb') as output:
                while True:
                    self.guard(start)
                    chunk = source.read(min(1024 * 1024, max(1, limit - written + 1)))
                    if not chunk:
                        break
                    if written + len(chunk) > limit:
                        raise LimitExceeded('解包输出超过文件大小或累计展开体积限制。')
                    output.write(chunk)
                    written += len(chunk)

        try:
            if kind == 'zip':
                with zipfile.ZipFile(path) as archive:
                    info = archive.getinfo(member)
                    if stat.S_ISLNK(info.external_attr >> 16):
                        raise ValueError('压缩包中的链接不跟随。')
                    copy(archive.open(info))
            else:
                with path.open('rb') as raw, tarfile.open(
                    fileobj=CheckedInput(raw, lambda: self.guard(start)), mode='r|*'
                ) as archive:
                    for info in self.tar_members(archive, start):
                        if info.name == member:
                            if not info.isfile():
                                raise ValueError('压缩包中的链接或特殊成员不跟随。')
                            copy(archive.extractfile(info))
                            break
                    else:
                        raise ValueError('TAR 中未找到指定成员。')
        finally:
            if target.exists():
                self.expanded += target.stat().st_size
