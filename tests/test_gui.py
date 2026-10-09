import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from lotfinder.gui import Window


def test_window_configuration_roundtrip(tmp_path):
    app = QApplication.instance() or QApplication([])
    window = Window()
    window.sources.clear()
    window.add_paths([str(tmp_path), str(tmp_path)])
    assert window.sources.count() == 1
    window.output.setText(str(tmp_path / "reports"))
    window.depth.setValue(5)
    window.header.setValue(2)
    config = window.config()
    assert config.max_depth == 5
    assert config.header_row == 2
    window.close()
