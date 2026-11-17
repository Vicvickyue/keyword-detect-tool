import csv
import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, LongTable, TableStyle
from lotfinder.report import chinese_font, safe_text
from . import TYPES


def write_pdf(result, target, full_list):
    font = chinese_font()
    style = ParagraphStyle('body', fontName=font, fontSize=9, leading=14, wordWrap='CJK')
    small = ParagraphStyle('small', parent=style, fontSize=8, leading=12)
    title = ParagraphStyle('title', parent=style, fontSize=20, leading=28, spaceAfter=12)
    heading = ParagraphStyle('heading', parent=style, keepWithNext=True, spaceAfter=6)
    def para(value, st=style):
        text = str(value).replace('\r\n', '\n').replace('\r', '\n')
        return Paragraph(escape(safe_text(text)).replace('\n', '<br/>'), st)
    story = [para('文件类型检查报告', title), para('任务状态：' + result['state']),
             para(f"检查条目 {result['files']} · 命中文件 {result['matched']} · 异常条目 {result['issues']}"),
             para(f"版本 {result['version']} · 开始 {result['started']} · 结束 {result['finished']}", small),
             para(result['scope'] + '。用途说明为业务分类，不表示文件内容已验证。', small),
             para('压缩包内部检查：' + ('开启' if result['archives'] else '关闭（结论不包含内部文件）'), small)]
    for source in result['sources']:
        story.append(para('扫描来源：' + source, small))
    if result['matched']:
        conclusion = '发现目标后缀文件。'
    elif result['state'] == '完成':
        conclusion = '在本次已完成的扫描范围内未发现目标后缀文件。'
    else:
        conclusion = '已检查范围内未发现目标后缀文件；存在未完成项，无法确认全部范围。'
    story += [Spacer(1, 8), para(conclusion)]
    summary = [['勾选后缀', '业务类型', '命中文件数']]
    summary += [[s, TYPES[s], str(n)] for s, n in result['counts'].items()]
    def table(rows, widths):
        t = LongTable([[para(v, small) for v in row] for row in rows], colWidths=widths,
                      repeatRows=1, splitByRow=1, splitInRow=1)
        t.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#DDECF0')),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F4F6F8')]),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('LEFTPADDING', (0, 0), (-1, -1), 6), ('RIGHTPADDING', (0, 0), (-1, -1), 6),
            ('TOPPADDING', (0, 0), (-1, -1), 5), ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ]))
        return t
    width = landscape(A4)[0] - 80
    story += [table(summary, [100, width - 200, 100]), Spacer(1, 12),
              para('完整文件清单' if full_list else '命中文件与异常清单', heading)]
    rows = [['文档路径', '文档名', '后缀', '命中', '检查情况', '说明']]
    for row in result['rows']:
        if full_list or row['matched'] or row['reason']:
            rows.append([row['directory'], row['name'], row['suffix'] or '无后缀',
                         '是' if row['matched'] else '否', row['status'], row['reason']])
    if len(rows) > 1:
        story.append(table(rows, [180, 180, 50, 35, 105, width - 550]))
    else:
        story.append(para('无命中或异常条目。'))
    story += [Spacer(1, 10), para('完整逐项记录见同名 CSV / JSONL。压缩包普通成员仅检查名称，未验证内容或 CRC；'
                                 '文件名后缀与实际格式是否一致不在本工具检测范围内。', small)]
    def footer(canvas, doc):
        canvas.setFont(font, 8)
        canvas.drawString(40, 23, '本地离线检测 · 按后缀查找')
        canvas.drawRightString(landscape(A4)[0] - 40, 23, f'第 {doc.page} 页')
    SimpleDocTemplate(str(target), pagesize=landscape(A4), leftMargin=40, rightMargin=40,
                      topMargin=36, bottomMargin=40, title='文件类型检查报告').build(
                          story, onFirstPage=footer, onLaterPages=footer)


def export(result, output, full_list=False):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime('%Y%m%d')
    for seq in range(1, 100):
        base = output / f'文件类型检查_{stamp}_{seq:02d}'
        lock = base.with_suffix('.lock')
        try:
            with lock.open('x'): pass
        except FileExistsError:
            continue
        published = []
        try:
            if any(base.with_suffix(s).exists() for s in ('.pdf', '.csv', '.jsonl')):
                continue
            with tempfile.TemporaryDirectory(prefix='.typecheck-', dir=output) as temp:
                tmp = Path(temp)
                write_pdf(result, tmp / 'report.pdf', full_list)
                with (tmp / 'report.csv').open('w', encoding='utf-8-sig', newline='') as f:
                    writer = csv.writer(f)
                    writer.writerow(['文档路径', '文档名', '后缀', '命中', '检查情况', '说明', '完整来源'])
                    for row in result['rows']:
                        # Prevent spreadsheet applications from evaluating untrusted names as formulas.
                        vals = [row['directory'], row['name'], row['suffix'], '是' if row['matched'] else '否',
                                row['status'], row['reason'], row['source']]
                        writer.writerow(["'" + v if v.lstrip().startswith(('=', '+', '-', '@')) else v for v in vals])
                with (tmp / 'report.jsonl').open('w', encoding='utf-8') as f:
                    f.write(json.dumps({k: v for k, v in result.items() if k != 'rows'}, ensure_ascii=False) + '\n')
                    for row in result['rows']:
                        f.write(json.dumps(row, ensure_ascii=False) + '\n')
                for suffix in ('.csv', '.jsonl', '.pdf'):
                    target = base.with_suffix(suffix)
                    publish = os.rename if os.name == 'nt' else os.link
                    publish(tmp / ('report' + suffix), target)
                    published.append(target)
            return base.with_suffix('.pdf')
        except Exception:
            for target in published: target.unlink(missing_ok=True)
            raise
        finally:
            lock.unlink(missing_ok=True)
    raise ValueError('当天序列号 01～99 已用完，请更换输出目录。')
