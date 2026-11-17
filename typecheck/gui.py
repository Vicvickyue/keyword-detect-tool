from pathlib import Path
from threading import Event
from PySide6.QtCore import QThread, Signal, QSettings, QUrl
from PySide6.QtGui import QDesktopServices, QFont, QFontDatabase
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QGridLayout, QLabel, QCheckBox, QPushButton, QListWidget, QFileDialog, QLineEdit,
    QSpinBox, QGroupBox, QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox, QProgressBar)
from . import TYPES, VERSION
from .engine import Config, execute


class Worker(QThread):
    progress = Signal(dict)
    result = Signal(str, dict)
    error = Signal(str)
    def __init__(self, config):
        super().__init__()
        self.config = config
        self.cancelled = Event()
    def run(self):
        try:
            path, result = execute(self.config, self.cancelled, self.progress.emit)
            self.result.emit(str(path), result)
        except Exception as exc:
            self.error.emit(str(exc))


class Window(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('文件类型检查工具 ' + VERSION)
        self.resize(1050, 850)
        self.settings = QSettings('FileTypeCheckTool', 'Desktop')
        self.worker = None
        self.report = ''
        self.setCentralWidget(QWidget())
        layout = QVBoxLayout(self.centralWidget())
        layout.setContentsMargins(22, 20, 22, 20)
        title = QLabel('文件类型检查'); title.setStyleSheet('font-size:26px;font-weight:bold;color:#173F51')
        layout.addWidget(title)
        layout.addWidget(QLabel('按最终后缀查找 · 不区分大小写 · 不验证真实格式或文件来源系统'))
        self.controls = QWidget(); form = QVBoxLayout(self.controls); form.setContentsMargins(0, 0, 0, 0)
        self.sources = QListWidget(); self.sources.setMaximumHeight(90)
        self.sources.setSelectionMode(QListWidget.ExtendedSelection)
        form.addWidget(self.sources)
        bar = QHBoxLayout(); form.addLayout(bar)
        self.button(bar, '添加文件', self.add_files)
        self.button(bar, '添加文件夹', self.add_folder)
        self.button(bar, '移除选中', self.remove)
        bar.addStretch()
        box = QGroupBox('选择需要检测的文件后缀'); grid = QGridLayout(box)
        self.checks = {}
        for i, (suffix, label) in enumerate(TYPES.items()):
            check = QCheckBox(suffix + '  ' + label)
            check.setChecked(self.settings.value('type_' + suffix, True, type=bool))
            self.checks[suffix] = check; grid.addWidget(check, i // 3, i % 3)
        form.addWidget(box)
        allbar = QHBoxLayout(); form.addLayout(allbar)
        self.button(allbar, '全选', lambda: self.select_all(True))
        self.button(allbar, '全不选', lambda: self.select_all(False)); allbar.addStretch()
        self.archives = QCheckBox('检查压缩包内部文件（按归档名称逐项检查）')
        self.archives.setChecked(self.settings.value('archives', True, type=bool)); form.addWidget(self.archives)
        line = QHBoxLayout(); form.addLayout(line)
        line.addWidget(QLabel('最大压缩层数'))
        self.depth = QSpinBox(); self.depth.setRange(5, 30); self.depth.setValue(self.settings.value('depth', 10, type=int)); line.addWidget(self.depth)
        self.full = QCheckBox('PDF 附完整文件清单（默认仅命中和异常；CSV 始终完整）'); line.addWidget(self.full)
        line = QHBoxLayout(); form.addLayout(line); line.addWidget(QLabel('报告输出目录'))
        self.output = QLineEdit(self.settings.value('output', str(Path.home() / 'Documents/文件类型检查报告')))
        line.addWidget(self.output); self.button(line, '选择目录', self.choose_output)
        layout.addWidget(self.controls)
        bar = QHBoxLayout(); layout.addLayout(bar)
        self.start_button = self.button(bar, '开始检查', self.start)
        self.start_button.setStyleSheet('background:#087F8C;color:white;font-weight:bold;padding:9px 22px')
        self.cancel_button = self.button(bar, '取消', self.cancel); self.cancel_button.setEnabled(False)
        bar.addStretch()
        self.pdf_button = self.button(bar, '打开 PDF', self.open_pdf); self.pdf_button.setEnabled(False)
        self.button(bar, '打开输出目录', self.open_output)
        self.progress = QProgressBar(); self.progress.setValue(0); layout.addWidget(self.progress)
        self.status = QLabel('就绪。只按后缀判断，.gds.txt 不会作为 .gds 命中。'); self.status.setWordWrap(True); layout.addWidget(self.status)
        self.table = QTableWidget(0, 5); self.table.setHorizontalHeaderLabels(['来源路径', '文档名', '后缀', '命中', '检查情况'])
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch); layout.addWidget(self.table)
        self.setStyleSheet(self.styleSheet() + 'QMainWindow{background:#F4F7FA} QGroupBox{font-weight:bold;padding-top:18px} QPushButton{padding:6px 12px} QCheckBox{padding:4px}')

    def button(self, layout, label, callback):
        b = QPushButton(label); b.clicked.connect(callback); layout.addWidget(b); return b
    def select_all(self, value):
        for check in self.checks.values(): check.setChecked(value)
    def add_paths(self, paths):
        existing = {self.sources.item(i).text().casefold() for i in range(self.sources.count())}
        for path in paths:
            if path.casefold() not in existing:
                self.sources.addItem(path); existing.add(path.casefold())
    def add_files(self): self.add_paths(QFileDialog.getOpenFileNames(self, '选择待检查文件')[0])
    def add_folder(self):
        p = QFileDialog.getExistingDirectory(self, '选择待检查目录')
        if p: self.add_paths([p])
    def remove(self):
        for item in self.sources.selectedItems(): self.sources.takeItem(self.sources.row(item))
    def choose_output(self):
        p = QFileDialog.getExistingDirectory(self, '选择独立的输出目录')
        if p: self.output.setText(p)
    def config(self):
        return Config([Path(self.sources.item(i).text()) for i in range(self.sources.count())], Path(self.output.text()),
                      {s for s, c in self.checks.items() if c.isChecked()}, self.archives.isChecked(), self.full.isChecked(), self.depth.value())
    def start(self):
        try:
            config = self.config(); config.validate()
        except Exception as exc:
            QMessageBox.warning(self, '请检查设置', str(exc)); return
        for s, c in self.checks.items(): self.settings.setValue('type_' + s, c.isChecked())
        self.settings.setValue('output', str(config.output)); self.settings.setValue('archives', config.archives); self.settings.setValue('depth', config.max_depth)
        self.report = ''; self.pdf_button.setEnabled(False); self.table.setRowCount(0)
        self.controls.setEnabled(False); self.start_button.setEnabled(False); self.cancel_button.setEnabled(True)
        self.progress.setRange(0, 0)
        self.worker = Worker(config)
        self.worker.progress.connect(self.on_progress); self.worker.result.connect(self.on_result)
        self.worker.error.connect(self.on_error); self.worker.finished.connect(self.finished); self.worker.start()
    def on_progress(self, data):
        self.status.setText(f"已检查 {data['files']} 条 · 命中 {data['matched']} 个\n{data['current']}")
    def on_result(self, path, result):
        self.report = path
        self.status.setText(f"{result['state']} · 命中 {result['matched']} 个 · 异常 {result['issues']} 条。PDF、CSV、JSONL 已保存。")
        rows = [r for r in result['rows'] if r['matched'] or r['reason']]
        self.table.setRowCount(len(rows))
        for i, row in enumerate(rows):
            for j, value in enumerate([row['directory'], row['name'], row['suffix'], '是' if row['matched'] else '否', row['status'] + ('：' + row['reason'] if row['reason'] else '')]):
                item = QTableWidgetItem(value); item.setToolTip(value); self.table.setItem(i, j, item)
        if not rows and not result['matched']:
            self.status.setText(self.status.text() + ' 在已检查范围内未发现目标后缀文件。')
    def on_error(self, error): self.status.setText('任务失败，未生成完整报告：' + error)
    def finished(self):
        self.controls.setEnabled(True); self.start_button.setEnabled(True); self.cancel_button.setEnabled(False)
        self.pdf_button.setEnabled(bool(self.report)); self.progress.setRange(0, 100); self.progress.setValue(100)
    def cancel(self):
        if self.worker and self.worker.isRunning():
            self.worker.cancelled.set(); self.cancel_button.setEnabled(False); self.status.setText('正在取消并保存结果，请稍候。')
    def open_pdf(self):
        if self.report: QDesktopServices.openUrl(QUrl.fromLocalFile(self.report))
    def open_output(self):
        path = Path(self.output.text()); path.mkdir(parents=True, exist_ok=True); QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.resolve())))
    def closeEvent(self, event):
        if self.worker and self.worker.isRunning(): self.cancel(); event.ignore()
        else: event.accept()


def main():
    app = QApplication([])
    font = Path('C:/Windows/Fonts/msyh.ttc')
    if font.exists(): QFontDatabase.addApplicationFont(str(font))
    app.setFont(QFont('Microsoft YaHei', 10))
    window = Window(); window.show(); return app.exec()
