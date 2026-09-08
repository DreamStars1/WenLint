param(
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$FrontendDist = Join-Path $ProjectRoot "wenlint\desktop_ui"
Push-Location $ProjectRoot
try {
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

    & $Python -m PyInstaller `
        --noconfirm `
        --clean `
        --onefile `
        --windowed `
        --name WenLint `
        --specpath build `
        --paths $ProjectRoot `
        --collect-all webview `
        --add-data "$FrontendDist;wenlint/desktop_ui" `
        scripts/wenlint_desktop_entry.py
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller build failed with exit code $LASTEXITCODE"
    }
    Write-Host "Built: $ProjectRoot\dist\WenLint.exe"
}
finally {
    Pop-Location
}
