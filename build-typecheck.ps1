param([string]$SevenZipDirectory = 'C:\Program Files\7-Zip')
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$pythonPath = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) { throw 'Create .venv and install requirements-dev.txt first.' }
New-Item -ItemType Directory -Path vendor/7zip -Force | Out-Null
foreach ($name in @('7z.exe','7z.dll','License.txt')) {
    Copy-Item -LiteralPath (Join-Path $SevenZipDirectory $name) -Destination vendor/7zip -Force
}
$env:QT_QPA_PLATFORM = 'offscreen'
& $pythonPath -m pytest -q
if ($LASTEXITCODE -ne 0) { throw 'Tests failed.' }
& $pythonPath -m PyInstaller --noconfirm --clean --windowed --onedir --name FileTypeCheckTool `
    --add-binary 'vendor/7zip/7z.exe;vendor/7zip' --add-binary 'vendor/7zip/7z.dll;vendor/7zip' `
    --add-data 'vendor/7zip/License.txt;vendor/7zip' `
    --exclude-module PySide6.QtWebEngineCore --exclude-module PySide6.QtWebEngineWidgets `
    --exclude-module PySide6.QtQml --exclude-module PySide6.QtQuick typecheck_main.py
if ($LASTEXITCODE -ne 0) { throw 'Packaging failed.' }
$package = Join-Path $PSScriptRoot 'dist\FileTypeCheckTool'
Copy-Item -LiteralPath TYPECHECK.md -Destination (Join-Path $package 'README.md') -Force
Copy-Item -LiteralPath THIRD_PARTY_NOTICES.md -Destination $package -Force
& $pythonPath tools/collect_licenses.py $package
if ($LASTEXITCODE -ne 0) { throw 'License collection failed.' }
Compress-Archive -LiteralPath $package -DestinationPath dist/FileTypeCheckTool-Windows-x64.zip -Force
Write-Output 'Ready: dist/FileTypeCheckTool-Windows-x64.zip'
