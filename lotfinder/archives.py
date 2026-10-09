import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from .models import LimitExceeded


def find_7zip(explicit=""):
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    candidates = [explicit, str(root / "vendor/7zip/7z.exe"), shutil.which("7z"),
                  r"C:\Program Files\7-Zip\7z.exe", r"C:\Program Files (x86)\7-Zip\7z.exe"]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return str(Path(candidate).resolve())
    raise RuntimeError("未找到 7-Zip。请使用完整便携包，或安装 7-Zip 后重试。")


class ArchiveReader:
    def __init__(self, config, check):
        self.config = config
        self.check = check
        self.expanded = 0
        self.executable = None

    def run(self, args, target, byte_limit):
        self.check()
        if not self.executable:
            self.executable = find_7zip(self.config.seven_zip)
        with target.open("wb") as out, tempfile.TemporaryFile() as err:
            process = subprocess.Popen([self.executable, *args], stdout=out, stderr=err,
                                       stdin=subprocess.DEVNULL,
                                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            start = time.monotonic()
            try:
                while True:
                    self.check()
                    if target.stat().st_size > byte_limit:
                        raise LimitExceeded("解压输出超过文件大小或累计展开体积限制。")
                    if time.monotonic() - start > self.config.archive_timeout:
                        raise LimitExceeded("压缩包操作超时，未完整扫描。")
                    if process.poll() is not None:
                        break
                    time.sleep(.05)
                if process.returncode:
                    err.seek(0)
                    details = err.read(4096).decode("utf-8", errors="replace").strip()
                    raise ValueError(f"7-Zip 返回 {process.returncode}（可能加密、缺卷或损坏）。{details}")
                if target.stat().st_size > byte_limit:
                    raise LimitExceeded("解压输出超过文件大小或累计展开体积限制。")
            finally:
                if process.poll() is None:
                    process.kill()
                process.wait()

    def members(self, path, temp_dir):
        listing = temp_dir / "listing.txt"
        self.run(["l", "-slt", "-ba", "-sccUTF-8", "-p__NO_PASSWORD_PROVIDED__", "--", str(path)],
                 listing, 16 * 1024**2)
        content = listing.read_text(encoding="utf-8-sig", errors="strict")
        members = []
        seen = set()
        for block in content.replace("\r\n", "\n").split("\n\n"):
            fields = {}
            for line in block.splitlines():
                if " = " in line:
                    key, value = line.split(" = ", 1)
                    fields[key] = value
            name = fields.get("Path")
            if name is None:
                continue
            if fields.get("Folder") == "+" or fields.get("Attributes", "").startswith("D"):
                continue
            if name in seen:
                raise ValueError("压缩包有重复成员路径，无法可靠逐文件计数。")
            seen.add(name)
            if fields.get("Symbolic Link") or fields.get("Hard Link") or fields.get("Mode", "").startswith("l"):
                members.append((name, -1, "压缩包中的链接不跟随。"))
                continue
            try:
                size = int(fields.get("Size", "0"))
            except ValueError:
                size = 0
            problem = "压缩成员已加密，未提供密码。" if fields.get("Encrypted") == "+" else ""
            members.append((name, size, problem))
            if len(members) > self.config.max_files:
                raise LimitExceeded("压缩包成员数超过任务限制。")
        return members

    def extract(self, path, member, target):
        remaining = self.config.max_expanded_bytes - self.expanded
        if remaining <= 0:
            raise LimitExceeded("累计展开体积已达到限制。")
        try:
            # stdout extraction never interprets member paths as destination paths.
            self.run(["e", "-so", "-spd", "-y", "-p__NO_PASSWORD_PROVIDED__", "--", str(path), member],
                     target, min(self.config.max_file_bytes, remaining))
        finally:
            if target.exists():
                self.expanded += target.stat().st_size
