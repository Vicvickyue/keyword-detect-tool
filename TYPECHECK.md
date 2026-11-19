# 文件类型检查工具

独立工具 v1.0.1，在 `feature/file-type-checker` 分支开发。原关键词检索工具保持独立。

## 使用

1. 下载并完整解压 `FileTypeCheckTool-Windows-x64.zip`，双击 `FileTypeCheckTool.exe`。保留 `_internal` 目录，无需安装 Python。
2. 添加文件或文件夹，勾选需要的后缀。13 项默认全选，支持全选、全不选，记住上次选择。
3. 选择独立的输出目录，按需启用压缩包内部检查，点击“开始检查”。
4. 查看界面的命中及异常清单，打开 PDF；同名 CSV、JSONL 始终包含完整记录。

可选后缀：`.src`、`.mdl`、`.gds`、`.gdsii`、`.oas`、`.oasis`、`.hss`、`.yml`、`.yaml`、`.tcl`、`.mca`、`.rdf`、`.hld`。
用途标签按业务约定显示，不是实际内容格式鉴定。

只比较最终后缀，忽略大小写：`A.GDS` 命中 `.gds`，`A.gds.txt` 不命中 `.gds`。
普通文件不读取内容，大型 GDS 也可仅检查名称。不检查关键词、不判断后缀真假，不推测 Windows/Linux 来源。
文件夹递归扫描；重复选择的相同路径去重；不跟随软链接或目录联接。输出目录及其后代自动排除。

## 压缩包

按压缩后缀识别并列出成员：ZIP、7Z、RAR、TAR、GZ、TGZ、BZ2、XZ、001；FILEPART 尝试按归档打开。
普通成员仅检查名称，不解压大型版图、不校验 CRC 或文件内容；只有嵌套压缩成员需要解压以读取下一层清单。
ZIP 文件被改为 `.txt` 时不尝试展开。Office 文件不会作为普通压缩包拆成内部 XML 清单。

ZIP 使用 Python 内置 zipfile；TAR、TGZ、TAR.GZ 使用 tarfile，其他格式继续使用随包提供的 7-Zip。缺少 TAR 结束零块但成员数据完整时允许读取；成员截断或结构异常时保留已读取清单并标记部分检查。读取完成仅表示后缀清单检查完成，不保证成员内容有效。

默认最大 10 层，界面可设 5～30 层；TGZ / TAR.GZ 作为一层处理。
默认扫描条目上限 10000、嵌套压缩成员解包上限 2 GiB、累计解包输出 10 GiB、单个 TAR 展开读取上限 10 GiB、单次归档操作 180 秒（内置读取在处理成员和数据块时检查超时及取消）。
上述解包大小限制不限制普通文件的后缀检查。达到任务限制会保留已有结果并标记未完整扫描。
常见根层分卷由首卷读取，其他分卷不重复展开。嵌套分卷集合不自动重组，标注未完成，需解包到同目录后重扫。
加密内容可见名称仍可按后缀命中，但标注内部未验证；若无法列目录则记为失败。损坏、超时、缺卷和取消均不能作为全范围无目标文件的证明。

## 报告

- PDF：选中类型逐项计数，默认展示命中文件与异常条目；可勾选完整文件清单。
- CSV：UTF-8 BOM 编码，可用 Excel 打开；每行独立保留完整路径。为避免公式执行，对以公式字符开头的值加文本前缀。
- JSONL：保留任务范围、选中后缀和未经 CSV 转义的原始记录。
- 命中数统计文件数量，不是文件内关键词次数。同一个目标文件只属于一个最终后缀。
- 文件名 `文件类型检查_YYYYMMDD_01.pdf`，同名 CSV / JSONL；序号 01～99，不覆盖旧报告。
- 关闭压缩检查时报告明确排除内部文件；未完成任务只能说明已检查范围内的结果。

## 源码及构建

使用原仓库 `.venv` 和 `requirements-dev.txt`。GUI：`.venv\Scripts\python.exe typecheck_main.py`。

```powershell
.venv\Scripts\python.exe typecheck_main.py --scan D:\input --output D:\reports --types .gds .oas .src
powershell -ExecutionPolicy Bypass -File build-typecheck.ps1
```

CLI 支持 `--no-archives`、`--depth 10`、`--full-list`。退出码 0 表示完成，2 表示取消/受限/异常，1 表示任务或报告错误。
构建前运行全部测试，单独生成 `dist/FileTypeCheckTool-Windows-x64.zip`，不替换原工具包。
