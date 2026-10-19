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
    window.full_file_list.setChecked(True)
    config = window.config()
    assert config.max_depth == 5
    assert config.header_row == 2
    assert config.include_full_file_list is True
    window.busy(True)
    assert not window.full_file_list.isEnabled()
    window.busy(False)
    window.close()
