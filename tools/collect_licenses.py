"""Include installed runtime dependency license notices in the portable package."""
import importlib.metadata
import shutil
import sys
from pathlib import Path

root = Path(sys.argv[1]) / "licenses"
root.mkdir(parents=True, exist_ok=True)
for candidate in (Path(sys.base_prefix) / "LICENSE_PYTHON.txt", Path(sys.base_prefix) / "LICENSE.txt"):
    if candidate.is_file():
        shutil.copy2(candidate, root / "PYTHON_LICENSE.txt")
        break
packages = ["PySide6-Essentials", "shiboken6", "openpyxl", "et-xmlfile", "python-calamine",
            "reportlab", "charset-normalizer", "pyahocorasick", "pillow"]
for name in packages:
    distribution = importlib.metadata.distribution(name)
    folder = root / name
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "METADATA.txt").write_text(distribution.read_text("METADATA") or "", encoding="utf-8")
    for file in distribution.files or []:
        if any(part.lower().startswith(("license", "copying", "notice")) for part in file.parts):
            source = Path(distribution.locate_file(file))
            if source.is_file():
                shutil.copy2(source, folder / ("_".join(file.parts)))
