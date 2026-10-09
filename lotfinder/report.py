import json
import os
import re
import tempfile
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph

from .models import RULE_NAMES


def chinese_font():
    if "ReportChinese" in pdfmetrics.getRegisteredFontNames():
        return "ReportChinese"
    root = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
    candidates = [root / "msyh.ttc", root / "simsun.ttc", root / "simhei.ttf"]
    for path in candidates:
        if path.exists():
            pdfmetrics.registerFont(TTFont("ReportChinese", str(path), subfontIndex=0))
            return "ReportChinese"
    raise RuntimeError("找不到中文字体，请确认 Windows 已安装微软雅黑或宋体。")


@contextmanager
def reserve_report(directory, date=None):
    directory.mkdir(parents=True, exist_ok=True)
    stamp = (date or datetime.now()).strftime("%Y%m%d")
    pattern = re.compile(rf"检索报告_{stamp}_([0-9]{{2}})\.pdf(?:\.lock)?$")
    used = [int(m.group(1)) for p in directory.iterdir() if (m := pattern.fullmatch(p.name))]
    sequence = max(used, default=0) + 1
    while sequence <= 99:
        path = directory / f"检索报告_{stamp}_{sequence:02d}.pdf"
        lock = path.with_suffix(".pdf.lock")
        try:
            with lock.open("x", encoding="utf-8") as stream:
                stream.write(str(os.getpid()))
        except FileExistsError:
            sequence += 1
            continue
        if path.exists():
            lock.unlink()
            sequence += 1
            continue
        try:
            yield path
        finally:
            lock.unlink(missing_ok=True)
        return
    raise ValueError("输出目录当天的两位序列号已用完（01–99），请更换输出目录。")


def safe_text(value):
    text = str(value)
    # Keep exact evidence recognizable without sending XML control characters into Paragraph.
    return "".join(ch if ch in "\n\t" or ord(ch) >= 32 else f"\\x{ord(ch):02x}" for ch in text)


class PDFWriter:
    def __init__(self, path):
        self.font = chinese_font()
        self.canvas = canvas.Canvas(str(path), pagesize=A4, pageCompression=1)
        self.canvas.setTitle("文件关键词检索报告")
        self.canvas.setAuthor("Keyword Report Tool")
        self.width, self.height = A4
        self.left = 44
        self.usable = self.width - 88
        self.page = 0
        self.styles = {
            "body": ParagraphStyle("body", fontName=self.font, fontSize=9, leading=14,
                                   wordWrap="CJK", alignment=TA_LEFT, textColor=colors.HexColor("#273344")),
            "small": ParagraphStyle("small", fontName=self.font, fontSize=8, leading=12,
                                    wordWrap="CJK", textColor=colors.HexColor("#57657A")),
            "title": ParagraphStyle("title", fontName=self.font, fontSize=23, leading=32,
                                    wordWrap="CJK", textColor=colors.HexColor("#14314A")),
            "heading": ParagraphStyle("heading", fontName=self.font, fontSize=13, leading=20,
                                      wordWrap="CJK", textColor=colors.HexColor("#087F8C")),
        }
        self.new_page()

    def new_page(self):
        if self.page:
            self.footer()
            self.canvas.showPage()
        self.page += 1
        self.canvas.setStrokeColor(colors.HexColor("#D5E0E7"))
        self.canvas.line(44, self.height - 40, self.width - 44, self.height - 40)
        self.canvas.setFont(self.font, 8)
        self.canvas.setFillColor(colors.HexColor("#57657A"))
        self.canvas.drawString(44, self.height - 30, "KEYWORD REPORT  /  文件内容检索")
        self.y = self.height - 58

    def footer(self):
        self.canvas.setFont(self.font, 8)
        self.canvas.setFillColor(colors.HexColor("#57657A"))
        self.canvas.drawString(44, 28, "本地生成 · 总次数完整统计 · 每文件每 ID 最多保留 5 处明细")
        self.canvas.drawRightString(self.width - 44, 28, f"第 {self.page} 页")

    def paragraph(self, value, style="body", highlight=""):
        text = safe_text(value)
        # Bound individual flowables; no content truncation, even for very long log lines.
        for start in range(0, max(1, len(text)), 2000):
            raw = text[start:start + 2000]
            if highlight:
                pattern = re.compile(re.escape(highlight), re.IGNORECASE)
                markup = ""
                previous = 0
                for match in pattern.finditer(raw):
                    markup += escape(raw[previous:match.start()])
                    markup += '<font color="#B54B08">' + escape(match.group()) + "</font>"
                    previous = match.end()
                markup += escape(raw[previous:])
            else:
                markup = escape(raw)
            markup = markup.replace("\t", "    ").replace("\n", "<br/>")
            # Preserve repeated spaces, while CJK wrapping still handles long strings.
            markup = markup.replace("  ", "&#160; ")
            item = Paragraph(markup or "&#160;", self.styles[style])
            queue = [item]
            while queue:
                para = queue.pop(0)
                available = self.y - 52
                _, height = para.wrap(self.usable, available)
                if height <= available:
                    para.drawOn(self.canvas, self.left, self.y - height)
                    self.y -= height + 4
                else:
                    parts = para.split(self.usable, available)
                    if parts:
                        first = parts.pop(0)
                        _, height = first.wrap(self.usable, available)
                        first.drawOn(self.canvas, self.left, self.y - height)
                        self.y -= height
                        queue = parts + queue
                    self.new_page()

    def heading(self, text):
        if self.y < 130:
            self.new_page()
        self.y -= 9
        self.paragraph(text, "heading")

    def ensure_space(self, height):
        if self.y - 52 < height:
            self.new_page()

    def save(self):
        self.footer()
        self.canvas.save()


def write_pdf(store, target):
    report = PDFWriter(target)
    meta, summary = store.metadata(), store.summary()
    report.paragraph("文件关键词检索报告", "title")
    report.paragraph(f"任务状态：{meta['state']}")
    report.paragraph(f"开始：{meta['started']}    结束：{meta['finished']}    版本：{meta['version']}", "small")
    report.heading("01 / 任务概览")
    report.paragraph(f"发现条目 {summary['files']}  |  压缩容器 {summary['archives']}  |  "
                     f"命中文件 {summary['matched']}  |  未完整扫描 {summary['incomplete']}")
    report.paragraph(f"所有规则匹配总次数：{summary['total']}（同一位置命中不同规则时分别计数）")
    for source in meta["sources"]:
        report.paragraph(f"扫描来源：{source}", "small")
    report.paragraph("启用规则：" + "、".join(RULE_NAMES[r] for r in meta["rules"]))
    settings = meta["settings"]
    report.paragraph(f"大小写：{'区分' if settings['case_sensitive'] else '不区分'}；词库匹配："
                     f"{'完整 ID' if settings['whole_id'] else '包含匹配'}；表头行：{settings['header_row']}；"
                     f"最大压缩深度：{settings['max_depth']}。", "small")
    report.paragraph("文本保存原始命中行；表格保存命中单元格、左一列、右一列及对应表头。"
                     "同一位置重复出现计入总次数，但上下文明细只保存一份。", "small")
    for warning in meta["warnings"]:
        report.paragraph(warning)
    for rule, info in meta["dictionaries"].items():
        report.paragraph(f"{RULE_NAMES[rule]} 词库：{info['path']}；关键词 {info['count']} 个；"
                         f"工作表 {info['sheet']}，A2 起。", "small")
        report.paragraph(f"SHA-256：{info['sha256']}", "small")
    report.heading("02 / 文件清单")
    report.paragraph("“完成 / 否”表示已扫描但没有命中；失败、跳过、受限等文件的总数仅为已观察到的次数。"
                     "压缩容器自身不重复计入成员命中次数。", "small")
    for file in store.files():
        report.ensure_space(75)
        hit = "是" if file["total"] else ("否" if file["status"] == "完成" else "未知 / 不适用")
        report.paragraph(f"[{file['id']}] {file['name']}")
        report.paragraph(f"后缀：{file['suffix'] or '无'}  |  识别类型：{file['kind']}  |  "
                         f"状态：{file['status']}  |  命中：{hit}  |  总次数：{file['total']}", "small")
        report.paragraph(f"来源：{file['source']}", "small")
        if file["error"]:
            report.paragraph(f"说明：{file['error']}", "small")
    report.heading("03 / 匹配明细")
    if not summary["total"]:
        report.paragraph("在已扫描的内容中未发现符合已启用规则的关键词。")
    for file in store.files():
        if not file["total"]:
            continue
        report.heading(f"文件 [{file['id']}] {file['name']}")
        report.paragraph(file["source"], "small")
        for hit in store.hits(file["id"]):
            evidence = store.evidence(file["id"], hit["rule"], hit["keyword"])
            report.ensure_space(85)
            report.paragraph(f"{RULE_NAMES[hit['rule']]}：{hit['keyword']}  |  "
                             f"总次数 {hit['total']}  |  明细 {len(evidence)} 处", highlight=hit["keyword"])
            for index, item in enumerate(evidence, 1):
                report.ensure_space(45)
                if item["type"] == "text":
                    report.paragraph(f"明细 {index} · 第 {item['line']} 行 · "
                                     f"本行出现 {item['occurrences']} 次 · 编码 {item['encoding']}", "small")
                    report.paragraph(item["text"], highlight=hit["keyword"])
                else:
                    report.paragraph(f"明细 {index} · {item['sheet']} · {item['column']}{item['row']} · "
                                     f"本单元格出现 {item['occurrences']} 次", "small")
                    for cell in item["cells"]:
                        report.ensure_space(40)
                        mark = "命中列" if cell["matched"] else "相邻列"
                        report.paragraph(f"{mark} {cell['column']} / 表头：{cell['header'] or '（无）'}", "small")
                        report.paragraph(cell["value"], highlight=hit["keyword"] if cell["matched"] else "")
            report.y -= 5
    report.save()


def write_log(store, target):
    with target.open("w", encoding="utf-8") as stream:
        def emit(data):
            stream.write(json.dumps(data, ensure_ascii=False) + "\n")
        emit({"type": "task", **store.metadata(), "summary": store.summary()})
        for file in store.files():
            emit({"type": "file", **dict(file)})
            for hit in store.hits(file["id"]):
                emit({"type": "hit", **dict(hit), "evidence": store.evidence(
                    file["id"], hit["rule"], hit["keyword"])})


def export_report(store, output):
    with reserve_report(output) as target:
        with tempfile.TemporaryDirectory(prefix=".report-", dir=output) as temp:
            pdf = Path(temp) / "report.pdf"
            log = Path(temp) / "report.jsonl"
            write_pdf(store, pdf)
            write_log(store, log)
            # Windows rename refuses to overwrite and also works on FAT/external drives.
            # POSIX rename would overwrite, so use exclusive hard-link publication there.
            publish = os.rename if os.name == "nt" else os.link
            log_target = target.with_suffix(".jsonl")
            publish(log, log_target)
            try:
                publish(pdf, target)
            except Exception:
                log_target.unlink(missing_ok=True)
                raise
        return target
