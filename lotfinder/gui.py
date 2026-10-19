import os
import sys
from pathlib import Path
from threading import Event

from PySide6.QtCore import QSettings, QThread, Signal, QUrl
from PySide6.QtGui import QDesktopServices, QFont, QFontDatabase
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QFileDialog, QFormLayout,
    QGridLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListWidget, QMainWindow,
    QMessageBox, QProgressBar, QPushButton, QSpinBox, QTextEdit, QVBoxLayout, QWidget)

from . import __version__
from .job import execute
from .models import DICT_RULES, RULE_NAMES, ScanConfig


class Worker(QThread):
    progress = Signal(dict)
    succeeded = Signal(str, dict, str)
    failed = Signal(str)

    def __init__(self, config):
        super().__init__()
        self.config = config
        self.cancel = Event()

    def run(self):
        try:
            path, summary, state = execute(self.config, self.cancel, self.progress.emit)
            self.succeeded.emit(str(path), summary, state)
        except Exception as exc:
            self.failed.emit(f"{type(exc).__name__}: {exc}")


class Window(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"文件关键词检索工具  {__version__}")
        self.resize(940, 840)
        self.settings = QSettings("KeywordReportTool", "Desktop")
        self.worker = None
        self.last_report = ""
        main = QWidget()
        layout = QVBoxLayout(main)
        layout.setContentsMargins(26, 22, 26, 22)
        title = QLabel("文件关键词检索")
        title.setObjectName("title")
        layout.addWidget(title)
        layout.addWidget(QLabel("本地离线处理  ·  多层压缩检索  ·  自动生成 PDF 报告"))

        self.input_group = QGroupBox("1  选择待检索内容")
        inputs = QVBoxLayout(self.input_group)
        self.sources = QListWidget()
        self.sources.setMaximumHeight(110)
        self.sources.setSelectionMode(QListWidget.ExtendedSelection)
        inputs.addWidget(self.sources)
        buttons = QHBoxLayout()
        self.button(buttons, "添加文件", self.add_files)
        self.button(buttons, "添加文件夹", self.add_folder)
        self.button(buttons, "移除选中", self.remove_sources)
        buttons.addStretch()
        inputs.addLayout(buttons)
        layout.addWidget(self.input_group)

        self.config_group = QGroupBox("2  词库与规则")
        config_layout = QVBoxLayout(self.config_group)
        config_layout.addWidget(QLabel("三个独立 Excel：第一个工作表，A1 为表头，A2 起每行一个关键词。"))
        form = QFormLayout()
        self.dictionary_edits = {}
        for rule in DICT_RULES:
            edit = QLineEdit(str(self.settings.value(rule, "")))
            edit.setPlaceholderText("未选择时，此词库规则不启用")
            row = QHBoxLayout()
            row.addWidget(edit)
            self.button(row, "选择 Excel", lambda checked=False, e=edit: self.choose_excel(e))
            form.addRow(RULE_NAMES[rule], row)
            self.dictionary_edits[rule] = edit
        config_layout.addLayout(form)
        rules = QHBoxLayout()
        self.rule_checks = {}
        for key, label in RULE_NAMES.items():
            check = QCheckBox(label)
            check.setChecked(self.settings.value("rule_" + key, True, type=bool))
            self.rule_checks[key] = check
            rules.addWidget(check)
        config_layout.addLayout(rules)
        layout.addWidget(self.config_group)

        self.advanced = QGroupBox("高级设置")
        self.advanced.setCheckable(True)
        self.advanced.setChecked(False)
        advanced = QGridLayout(self.advanced)
        self.case_sensitive = QCheckBox("区分大小写")
        self.case_sensitive.setChecked(self.settings.value("case_sensitive", True, type=bool))
        self.whole_id = QCheckBox("词库按完整 ID 匹配")
        self.whole_id.setChecked(self.settings.value("whole_id", True, type=bool))
        advanced.addWidget(self.case_sensitive, 0, 0, 1, 2)
        advanced.addWidget(self.whole_id, 0, 2, 1, 2)
        self.header = self.spin(0, 1000, "header_row", 1)
        self.depth = self.spin(5, 30, "max_depth", 10)
        self.file_size = self.spin(1, 102400, "file_mb", 2048)
        self.total_size = self.spin(1, 1024000, "expanded_mb", 10240)
        for row, (label, widget, label2, widget2) in enumerate([
            ("表头行（0 = 无表头）", self.header, "最大压缩层数", self.depth),
            ("单文件上限（MiB）", self.file_size, "累计展开上限（MiB）", self.total_size)], 1):
            advanced.addWidget(QLabel(label), row, 0)
            advanced.addWidget(widget, row, 1)
            advanced.addWidget(QLabel(label2), row, 2)
            advanced.addWidget(widget2, row, 3)
        advanced_widgets = [advanced.itemAt(i).widget() for i in range(advanced.count())]
        for widget in advanced_widgets:
            widget.setVisible(False)
        self.advanced.toggled.connect(lambda visible: [widget.setVisible(visible) for widget in advanced_widgets])
        layout.addWidget(self.advanced)

        output_row = QHBoxLayout()
        output_row.addWidget(QLabel("报告输出目录"))
        self.output = QLineEdit(str(self.settings.value("output", str(Path.home() / "Documents/关键词检索报告"))))
        output_row.addWidget(self.output)
        self.output_button = self.button(output_row, "选择目录", self.choose_output)
        layout.addLayout(output_row)
        self.match_details = QCheckBox("输出匹配明细（原文及上下文，默认不输出；JSONL 始终保留明细）")
        self.match_details.setChecked(self.settings.value("include_match_details", False, type=bool))
        layout.addWidget(self.match_details)
        actions = QHBoxLayout()
        self.start_button = self.button(actions, "开始检索", self.start)
        self.start_button.setObjectName("primary")
        self.cancel_button = self.button(actions, "取消", self.cancel)
        self.cancel_button.setEnabled(False)
        actions.addStretch()
        self.open_pdf = self.button(actions, "打开 PDF", self.open_report)
        self.open_pdf.setEnabled(False)
        self.button(actions, "打开输出目录", self.open_output)
        layout.addLayout(actions)
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)
        self.status = QLabel("就绪。文件将只读检索；每个文件每个 ID 最多记录 5 处明细，总次数不截断。")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.details = QTextEdit()
        self.details.setReadOnly(True)
        self.details.setMaximumHeight(95)
        layout.addWidget(self.details)
        self.setCentralWidget(main)
        self.setStyleSheet("""
            QMainWindow {background: #F4F7FA;} QWidget {font-size: 13px; color: #24364B;}
            QLabel#title {font-size: 26px; font-weight: 600; color: #153450;}
            QGroupBox {background: white; border: 1px solid #D6E0E9; border-radius: 7px;
                       margin-top: 14px; padding: 14px 12px 10px;}
            QGroupBox::title {subcontrol-origin: margin; left: 12px; padding: 0 6px;}
            QLineEdit, QListWidget, QTextEdit, QSpinBox {background: white; border: 1px solid #C9D5E0;
                       border-radius: 4px; padding: 5px; selection-background-color: #087F8C;}
            QPushButton {background: #E8EFF4; border: 1px solid #C9D5E0; border-radius: 5px; padding: 7px 14px;}
            QPushButton:hover {background: #DAE8F0;} QPushButton:disabled {color: #98A6B4;}
            QPushButton#primary {background: #087F8C; color: white; border: none; min-width: 120px;}
            QProgressBar {border: none; background: #DEE7EE; border-radius: 4px; height: 10px; text-align: center;}
            QProgressBar::chunk {background: #087F8C; border-radius: 4px;}
        """)
        for source in self.settings.value("sources", [], type=list):
            if Path(source).exists():
                self.sources.addItem(source)

    @staticmethod
    def button(layout, text, handler):
        button = QPushButton(text)
        button.clicked.connect(handler)
        layout.addWidget(button)
        return button

    def spin(self, low, high, key, default):
        widget = QSpinBox()
        widget.setRange(low, high)
        widget.setValue(self.settings.value(key, default, type=int))
        return widget

    def add_files(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "选择待检索文件", "", "所有文件 (*)")
        self.add_paths(paths)

    def add_paths(self, paths):
        existing = {self.sources.item(i).text() for i in range(self.sources.count())}
        for path in paths:
            if path not in existing:
                self.sources.addItem(path)
                existing.add(path)

    def add_folder(self):
        path = QFileDialog.getExistingDirectory(self, "选择待检索目录")
        if path:
            self.add_paths([path])

    def remove_sources(self):
        for item in self.sources.selectedItems():
            self.sources.takeItem(self.sources.row(item))

    def choose_excel(self, edit):
        path, _ = QFileDialog.getOpenFileName(self, "选择 Excel 词库", "", "Excel (*.xlsx *.xlsm)")
        if path:
            edit.setText(path)

    def choose_output(self):
        path = QFileDialog.getExistingDirectory(self, "选择报告输出目录", self.output.text())
        if path:
            self.output.setText(path)

    def config(self):
        return ScanConfig(
            sources=[Path(self.sources.item(i).text()) for i in range(self.sources.count())],
            output=Path(self.output.text().strip()),
            dictionaries={k: Path(e.text().strip()) for k, e in self.dictionary_edits.items() if e.text().strip()},
            enabled=[k for k, e in self.rule_checks.items() if e.isChecked()],
            case_sensitive=self.case_sensitive.isChecked(), whole_id=self.whole_id.isChecked(),
            header_row=self.header.value(), max_depth=self.depth.value(),
            max_file_bytes=self.file_size.value() * 1024**2,
            max_expanded_bytes=self.total_size.value() * 1024**2,
            include_match_details=self.match_details.isChecked())

    def start(self):
        try:
            if not self.output.text().strip():
                raise ValueError("请选择报告输出目录。")
            config = self.config()
            config.validate()
        except Exception as exc:
            QMessageBox.warning(self, "请检查配置", str(exc))
            return
        self.save_settings(config)
        self.details.clear()
        self.busy(True)
        self.worker = Worker(config)
        self.worker.progress.connect(self.on_progress)
        self.worker.succeeded.connect(self.on_success)
        self.worker.failed.connect(self.on_error)
        self.worker.finished.connect(lambda: self.busy(False))
        self.worker.start()

    def save_settings(self, config):
        self.settings.setValue("sources", [str(p) for p in config.sources])
        self.settings.setValue("output", str(config.output))
        self.settings.setValue("include_match_details", config.include_match_details)
        for key, edit in self.dictionary_edits.items():
            self.settings.setValue(key, edit.text())
        for key, check in self.rule_checks.items():
            self.settings.setValue("rule_" + key, check.isChecked())
        for key, value in {"case_sensitive": config.case_sensitive, "whole_id": config.whole_id,
            "header_row": config.header_row, "max_depth": config.max_depth,
            "file_mb": self.file_size.value(), "expanded_mb": self.total_size.value()}.items():
            self.settings.setValue(key, value)

    def busy(self, busy):
        for widget in (self.input_group, self.config_group, self.advanced, self.output, self.output_button,
                       self.start_button, self.match_details):
            widget.setEnabled(not busy)
        self.cancel_button.setEnabled(busy)
        self.open_pdf.setEnabled(not busy and bool(self.last_report))
        self.progress_bar.setRange(0, 0 if busy else 100)
        if not busy:
            self.progress_bar.setValue(100)

    def cancel(self):
        if self.worker:
            self.worker.cancel.set()
            self.cancel_button.setEnabled(False)
            self.status.setText("正在取消；将为已完成的检索内容生成标注为未完成的报告。")

    def on_progress(self, data):
        self.status.setText(f"发现条目 {data['files']} · 命中文件 {data['matched']} · 匹配次数 {data['total']}")
        self.details.append(data["current"])

    def on_success(self, path, summary, state):
        self.last_report = path
        self.status.setText(f"{state}。命中文件 {summary['matched']}，总次数 {summary['total']}。")
        self.details.append("PDF 已生成：" + path)

    def on_error(self, error):
        self.status.setText("任务失败，未生成完整报告。")
        self.details.append(error)
        QMessageBox.critical(self, "检索失败", error)

    def open_report(self):
        if self.last_report:
            QDesktopServices.openUrl(QUrl.fromLocalFile(self.last_report))

    def open_output(self):
        path = Path(self.output.text())
        path.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.resolve())))

    def closeEvent(self, event):
        if self.worker and self.worker.isRunning():
            self.cancel()
            event.ignore()
            self.status.setText("正在停止并保存结果，请任务结束后再关闭窗口。")
        else:
            event.accept()


def main():
    app = QApplication(sys.argv)
    font_path = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts/msyh.ttc"
    if font_path.exists():
        QFontDatabase.addApplicationFont(str(font_path))
    app.setFont(QFont("Microsoft YaHei", 10))
    window = Window()
    window.show()
    return app.exec()
