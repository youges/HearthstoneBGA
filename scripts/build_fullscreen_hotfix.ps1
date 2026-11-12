$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $taskRoot
$taskStage = Join-Path $taskRoot 'build\fullscreen-hotfix-0.2.1'
$taskPreviousPath = $env:PATH
$taskPreviousCache = $env:PYINSTALLER_CONFIG_DIR
$taskPythonBase = & "$taskRoot\.venv\Scripts\python.exe" -c 'import sys; print(sys.base_prefix)'
try {
    $env:PATH = @("$taskRoot\.venv\Scripts", $taskPythonBase, "$env:WINDIR\System32", "$env:WINDIR", "$env:WINDIR\System32\Wbem") -join ';'
    $env:PYINSTALLER_CONFIG_DIR = Join-Path $taskRoot 'build\fullscreen-hotfix-cache'
    & "$taskRoot\.venv\Scripts\python.exe" -m PyInstaller --clean --noconfirm --windowed --onedir --name HearthstoneBGA --icon "$taskRoot\assets\ui\app-icon.ico" --paths src --distpath $taskStage --workpath "$taskRoot\build\fullscreen-hotfix-work" --specpath "$taskRoot\build\fullscreen-hotfix-work" --collect-all rapidocr --collect-all onnxruntime --hidden-import mss.windows run.py
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller build failed' }
} finally {
    $env:PATH = $taskPreviousPath
    $env:PYINSTALLER_CONFIG_DIR = $taskPreviousCache
}
$taskDestination = Join-Path $taskStage 'HearthstoneBGA'
foreach ($taskFolder in @('assets','profiles','docs')) {
    Copy-Item -LiteralPath (Join-Path $taskRoot $taskFolder) -Destination $taskDestination -Recurse -Force
}
Write-Output "Built hotfix: $taskDestination"
