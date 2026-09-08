$ErrorActionPreference = "Stop"

$DemoRoot = $PSScriptRoot
$ProjectRoot = Split-Path -Parent $DemoRoot
$Candidates = @(
    (Join-Path $DemoRoot "WenLint.exe"),
    (Join-Path $ProjectRoot "WenLint.exe"),
    (Join-Path $ProjectRoot "dist-0.5.0-final\WenLint.exe"),
    (Join-Path $ProjectRoot "dist\WenLint.exe")
)

$Executable = $Candidates |
    Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } |
    Select-Object -First 1

if (-not $Executable) {
    throw "未找到 WenLint.exe。请将 Release 中的 EXE 放入 demo 目录，或先运行 scripts/build-windows.ps1。"
}

Start-Process -FilePath $Executable -WorkingDirectory $DemoRoot
Write-Host "已启动：$Executable"
Write-Host "待审查文件：$(Join-Path $DemoRoot 'review-me.md')"
Write-Host "演示工作区：$(Join-Path $DemoRoot 'workspace')"
