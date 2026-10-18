$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$portableExecutable = Join-Path $projectRoot 'dist\HearthstoneBGA\HearthstoneBGA.exe'
foreach ($runningAssistant in @(Get-Process HearthstoneBGA -ErrorAction SilentlyContinue)) {
    if ($runningAssistant.Path -eq $portableExecutable) { throw 'Close the portable assistant before rebuilding; user data must be idle.' }
}
$portableData = Join-Path $projectRoot 'dist\HearthstoneBGA\data'
$portableBackup = $null
if (Test-Path -LiteralPath $portableData) {
    $portableBackup = Join-Path $projectRoot ('data\release-backups\' + (Get-Date -Format 'yyyyMMdd-HHmmss-fff'))
    New-Item -ItemType Directory -Force -Path $portableBackup | Out-Null
    Copy-Item -LiteralPath $portableData -Destination "$portableBackup\data" -Recurse
    foreach ($folder in @('profiles','assets')) {
        $existingFolder = Join-Path $projectRoot "dist\HearthstoneBGA\$folder"
        if (Test-Path -LiteralPath $existingFolder) {
            Copy-Item -LiteralPath $existingFolder -Destination "$portableBackup\$folder" -Recurse
        }
    }
    Write-Output "Saved previous portable data: $portableBackup"
}
$buildPreviousPath = $env:PATH
$buildPreviousCache = $env:PYINSTALLER_CONFIG_DIR
$buildPythonBase = & "$projectRoot\.venv\Scripts\python.exe" -c 'import sys; print(sys.base_prefix)'
try {
    # Keep unrelated bundled tools (notably Poppler's incompatible icuuc.dll)
    # out of PyInstaller's DLL search. This modifies only this build process.
    $env:PATH = @("$projectRoot\.venv\Scripts", "$buildPythonBase", "$env:WINDIR\System32", "$env:WINDIR", "$env:WINDIR\System32\Wbem") -join ';'
    $env:PYINSTALLER_CONFIG_DIR = Join-Path $projectRoot 'build\pyinstaller-cache'
    & "$projectRoot\.venv\Scripts\python.exe" -m PyInstaller --clean --noconfirm --windowed --onedir --name HearthstoneBGA --paths src --distpath "$projectRoot\dist" --workpath "$projectRoot\build" --collect-all rapidocr --collect-all onnxruntime --hidden-import mss.windows run.py
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller build failed' }
} finally {
    $env:PATH = $buildPreviousPath
    $env:PYINSTALLER_CONFIG_DIR = $buildPreviousCache
}
$destination = Join-Path $projectRoot 'dist\HearthstoneBGA'
if ($portableBackup) {
    Copy-Item -LiteralPath "$portableBackup\data" -Destination $destination -Recurse -Force
}
if (-not (Test-Path -LiteralPath "$destination\data\settings.json")) {
    & "$projectRoot\.venv\Scripts\python.exe" -c 'import sys; from pathlib import Path; sys.path.insert(0,"src"); from bga.config import Config; Config(profile_path="profiles/pc-integration.json",focus_on_start=True,recover_focus=True,inspect_hand_cards=True,max_matches=1).save(Path(sys.argv[1]))' "$destination\data\settings.json"
    if ($LASTEXITCODE -ne 0) { throw 'Default portable settings could not be created' }
}
New-Item -ItemType Directory -Force -Path "$destination\profiles", "$destination\docs" | Out-Null
New-Item -ItemType Directory -Force -Path "$destination\assets" | Out-Null
Copy-Item -LiteralPath "$projectRoot\assets\ui" -Destination "$destination\assets" -Recurse -Force
Copy-Item -LiteralPath "$projectRoot\profiles\default.json" -Destination "$destination\profiles\default.json"
if (Test-Path -LiteralPath "$projectRoot\profiles\pc-integration.json") {
    Copy-Item -LiteralPath "$projectRoot\profiles\pc-integration.json" -Destination "$destination\profiles\pc-integration.json"
}
if (Test-Path -LiteralPath "$projectRoot\profiles\live-partial.json") {
    Copy-Item -LiteralPath "$projectRoot\profiles\live-partial.json" -Destination "$destination\profiles\live-partial.json"
}
if (Test-Path -LiteralPath "$projectRoot\assets\templates\live") {
    New-Item -ItemType Directory -Force -Path "$destination\assets\templates" | Out-Null
    Copy-Item -LiteralPath "$projectRoot\assets\templates\live" -Destination "$destination\assets\templates" -Recurse -Force
}
Copy-Item -Path "$projectRoot\docs\*.md" -Destination "$destination\docs"
Copy-Item -LiteralPath "$projectRoot\research\ocr_model_manifest.json" -Destination "$destination\docs\ocr_model_manifest.json"
if (Test-Path -LiteralPath "$projectRoot\THIRD_PARTY_NOTICES") {
    Copy-Item -LiteralPath "$projectRoot\THIRD_PARTY_NOTICES" -Destination $destination -Recurse
}
if ($portableBackup) {
    & "$projectRoot\.venv\Scripts\python.exe" "$projectRoot\scripts\compact_build_backup.py" "$portableBackup"
    if ($LASTEXITCODE -ne 0) { throw 'Backup cleanup failed; full recovery data was retained.' }
}
Write-Output "Built: $destination\HearthstoneBGA.exe"
