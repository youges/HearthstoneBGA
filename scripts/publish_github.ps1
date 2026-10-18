param([string]$Repository = 'youges/HearthstoneBGA')
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$releaseRoot = Join-Path $projectRoot 'release\v0.2.0'
$verification = Join-Path $releaseRoot 'package-verification.json'
if (-not (Test-Path -LiteralPath $verification)) { throw 'Run package_release.py first.' }
$report = Get-Content -LiteralPath $verification -Raw | ConvertFrom-Json
if (-not $report.passed) { throw 'Package validation has not passed.' }
if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
    throw 'Install GitHub CLI from https://cli.github.com, then run gh auth login.'
}
& gh auth status
if ($LASTEXITCODE -ne 0) { throw 'Run gh auth login first, then retry this script.' }
$sourceRoot = Join-Path $report.staging 'HearthstoneBGA-source'
if (-not (Test-Path -LiteralPath $sourceRoot)) { throw 'Source staging directory is missing.' }
Set-Location -LiteralPath $sourceRoot
if (-not (Test-Path -LiteralPath '.git')) {
    & git init -b main
    & git config user.name 'youges'
    & git config user.email '96408349+youges@users.noreply.github.com'
    & git add --all
    & git commit -m 'Release 0.2.0: resolution adaptation and Battle.net detection'
    if ($LASTEXITCODE -ne 0) { throw 'Source commit failed.' }
}
& gh repo view $Repository --json name 2>$null
if ($LASTEXITCODE -ne 0) {
    & gh repo create $Repository --public --source . --remote origin --push --description 'Windows 酒馆战棋桌面助手：自动适配分辨率、战网路径检测与对局记录'
    if ($LASTEXITCODE -ne 0) { throw 'Repository creation failed.' }
} else {
    if (-not (& git remote get-url origin 2>$null)) { & git remote add origin "https://github.com/$Repository.git" }
    & git push -u origin main
    if ($LASTEXITCODE -ne 0) { throw 'Push failed; remote history was not overwritten.' }
}
$notes = Join-Path $releaseRoot 'RELEASE_NOTES.md'
$files = @((Join-Path $releaseRoot 'HearthstoneBGA-0.2.0-windows-x64.zip'),
           (Join-Path $releaseRoot 'HearthstoneBGA-0.2.0-source.zip'),
           (Join-Path $releaseRoot 'SHA256SUMS.txt'))
& gh release create v0.2.0 @files --repo $Repository --title 'HearthstoneBGA 0.2.0（开发测试版）' --notes-file $notes --prerelease
if ($LASTEXITCODE -ne 0) { throw 'Release upload failed. Source repository may already exist.' }
& gh release view v0.2.0 --repo $Repository --json url,assets
