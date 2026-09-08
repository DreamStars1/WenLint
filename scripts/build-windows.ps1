param(
    [string]$Python = "python",
    [switch]$SkipFrontend,
    [string]$OutputDirectory = "dist"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$FrontendDist = Join-Path $ProjectRoot "wenlint\desktop_ui"
$DesktopDist = Join-Path $ProjectRoot $OutputDirectory
Push-Location $ProjectRoot
try {
    if (-not $SkipFrontend) {
        Push-Location desktop-ui
        try {
            pnpm install --frozen-lockfile
            if ($LASTEXITCODE -ne 0) { throw "Frontend dependency installation failed" }
            pnpm run build
            if ($LASTEXITCODE -ne 0) { throw "Vue build failed" }
        }
        finally {
            Pop-Location
        }
    }
    if (-not (Test-Path -LiteralPath (Join-Path $FrontendDist "index.html"))) {
        throw "Frontend assets are missing; build desktop-ui first"
    }

    & $Python scripts/collect-licenses.py
    if ($LASTEXITCODE -ne 0) { throw "Dependency notice collection failed" }

    & $Python -m PyInstaller `
        --noconfirm `
        --clean `
        --onedir `
        --windowed `
        --name WenLint `
        --distpath $DesktopDist `
        --specpath build `
        --paths $ProjectRoot `
        --collect-all webview `
        --add-data "$ProjectRoot/build/third-party-licenses;third-party-licenses" `
        --add-data "$FrontendDist;wenlint/desktop_ui" `
        scripts/wenlint_desktop_entry.py
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller build failed with exit code $LASTEXITCODE"
    }
    Copy-Item -LiteralPath LICENSE -Destination (Join-Path $DesktopDist 'WenLint/LICENSE.txt')
    Write-Host "Built: $DesktopDist\WenLint\WenLint.exe (keep the entire folder)"
}
finally {
    Pop-Location
}
