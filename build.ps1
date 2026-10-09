param(
    [string]$SevenZipDirectory = 'C:\Program Files\7-Zip',
    [switch]$SkipInstall
)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$pythonPath = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Failed to create virtual environment.' }
}
if (-not $SkipInstall) {
    & $pythonPath -m pip install -r requirements-dev.txt
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
}
$vendorDirectory = Join-Path $PSScriptRoot 'vendor\7zip'
New-Item -ItemType Directory -Path $vendorDirectory -Force | Out-Null
foreach ($fileName in @('7z.exe', '7z.dll', 'License.txt')) {
    $sourceFile = Join-Path $SevenZipDirectory $fileName
    if (-not (Test-Path -LiteralPath $sourceFile)) { throw "Missing $sourceFile" }
    Copy-Item -LiteralPath $sourceFile -Destination $vendorDirectory -Force
}
& $pythonPath -m pytest -q
if ($LASTEXITCODE -ne 0) { throw 'Tests failed.' }
& $pythonPath -m PyInstaller --noconfirm --clean --windowed --onedir --name KeywordReportTool `
    --add-binary 'vendor/7zip/7z.exe;vendor/7zip' `
    --add-binary 'vendor/7zip/7z.dll;vendor/7zip' `
    --add-data 'vendor/7zip/License.txt;vendor/7zip' `
    --collect-all python_calamine --hidden-import ahocorasick `
    --exclude-module PySide6.QtWebEngineCore --exclude-module PySide6.QtWebEngineWidgets `
    --exclude-module PySide6.QtWebEngineQuick --exclude-module PySide6.QtPdf `
    --exclude-module PySide6.QtQml --exclude-module PySide6.QtQuick `
    --exclude-module PySide6.QtQuickWidgets main.py
if ($LASTEXITCODE -ne 0) { throw 'Packaging failed.' }
$distribution = Join-Path $PSScriptRoot 'dist\KeywordReportTool'
Copy-Item -LiteralPath 'README.md', 'THIRD_PARTY_NOTICES.md' -Destination $distribution -Force
& $pythonPath tools/create_samples.py $distribution
if ($LASTEXITCODE -ne 0) { throw 'Creating examples failed.' }
& $pythonPath tools/collect_licenses.py $distribution
if ($LASTEXITCODE -ne 0) { throw 'Creating package resources failed.' }
$zipPath = Join-Path $PSScriptRoot 'dist\KeywordReportTool-Windows-x64.zip'
Compress-Archive -LiteralPath $distribution -DestinationPath $zipPath -Force
Get-FileHash -LiteralPath $zipPath -Algorithm SHA256
Write-Output "Ready: $zipPath"
