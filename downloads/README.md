# Windows 便携版下载

版本：v1.3.1。支持 Windows 10/11 x64，支持 SQLite `.db3` 检索；默认输出六列完整结果表，可勾选输出匹配明细。

**[点击下载 Windows 便携包](https://github.com/Vicvickyue/keyword-detect-tool/raw/refs/heads/main/downloads/KeywordReportTool-Windows-x64.zip)**

如果直接链接不能下载，请打开 [ZIP 文件页面](KeywordReportTool-Windows-x64.zip)，点击 **Download raw file** 下载完整文件。私有仓库需要登录有访问权限的账号。

1. 将 ZIP 完整解压到本地文件夹。
2. 双击文件夹中的 `KeywordReportTool.exe`，无需安装 Python 或 Excel。
3. 保留 EXE 旁的 `_internal` 文件夹，它包含运行依赖；不要只复制 EXE。
4. 使用 `词库模板` 填写自己的关键词，或先使用 `示例` 试运行。

这里的 ZIP 是打包后的程序；GitHub 的 **Code → Download ZIP** 下载的是整个源码仓库。

完整性校验文件：[KeywordReportTool-Windows-x64.zip.sha256](KeywordReportTool-Windows-x64.zip.sha256)。
可在 PowerShell 中运行 `Get-FileHash .\KeywordReportTool-Windows-x64.zip -Algorithm SHA256` 对照校验值。
