$ErrorActionPreference = "Stop"

$DemoRoot = $PSScriptRoot
$ProjectRoot = Split-Path -Parent $DemoRoot
$Executable = Join-Path $DemoRoot "WenLint.exe"
if (-not (Test-Path -LiteralPath $Executable -PathType Leaf)) {
    $BuildCandidates = @(
        (Join-Path $ProjectRoot "WenLint.exe"),
        (Join-Path $ProjectRoot "dist\WenLint.exe")
    )
    $BuildCandidates += Get-ChildItem -LiteralPath $ProjectRoot -Directory |
        Where-Object { $_.Name -like "dist-*" } |
        ForEach-Object { Join-Path $_.FullName "WenLint.exe" }
    $Executable = $BuildCandidates |
        Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } |
        ForEach-Object { Get-Item -LiteralPath $_ } |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1 -ExpandProperty FullName
}

if (-not $Executable) {
    throw "未找到 WenLint.exe。请将 Release 中的 EXE 放入 demo 目录，或先运行 scripts/build-windows.ps1。"
}

Start-Process -FilePath $Executable -WorkingDirectory $DemoRoot
Write-Host "已启动：$Executable"
Write-Host "待审查文件：$(Join-Path $DemoRoot 'review-me.md')"
Write-Host "演示工作区：$(Join-Path $DemoRoot 'workspace')"
