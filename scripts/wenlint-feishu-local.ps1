# Run the repository's Feishu adapter without depending on the Codex process PATH.
# All arguments are forwarded unchanged to `python -m wenlint.feishu.cli`.

$resolvedLarkCli = $env:WENLINT_LARK_CLI

if ([string]::IsNullOrWhiteSpace($resolvedLarkCli)) {
    $nvmSymlink = $env:NVM_SYMLINK
    if ([string]::IsNullOrWhiteSpace($nvmSymlink)) {
        $nvmSymlink = [Environment]::GetEnvironmentVariable('NVM_SYMLINK', 'User')
    }
    if (-not [string]::IsNullOrWhiteSpace($nvmSymlink)) {
        $nvmCandidate = Join-Path $nvmSymlink 'lark-cli.cmd'
        if (Test-Path -LiteralPath $nvmCandidate -PathType Leaf) {
            $resolvedLarkCli = $nvmCandidate
        }
    }
}

if ([string]::IsNullOrWhiteSpace($resolvedLarkCli)) {
    $pathCommand = Get-Command lark-cli.cmd -ErrorAction SilentlyContinue
    if ($null -eq $pathCommand) {
        $pathCommand = Get-Command lark-cli -ErrorAction SilentlyContinue
    }
    if ($null -ne $pathCommand) {
        $resolvedLarkCli = $pathCommand.Source
        if ([IO.Path]::GetExtension($resolvedLarkCli) -eq '') {
            $cmdCandidate = "$resolvedLarkCli.cmd"
            if (Test-Path -LiteralPath $cmdCandidate -PathType Leaf) {
                $resolvedLarkCli = $cmdCandidate
            }
        }
    }
}

if ([string]::IsNullOrWhiteSpace($resolvedLarkCli) -or
    -not (Test-Path -LiteralPath $resolvedLarkCli -PathType Leaf)) {
    throw 'lark-cli was not found. Activate the configured NVM version or set WENLINT_LARK_CLI to the executable path.'
}

$previousLarkCli = $env:WENLINT_LARK_CLI
$wenlintExitCode = 1

try {
    $env:WENLINT_LARK_CLI = $resolvedLarkCli
    & python -m wenlint.feishu.cli @args
    $wenlintExitCode = $LASTEXITCODE
}
finally {
    if ($null -eq $previousLarkCli) {
        Remove-Item Env:WENLINT_LARK_CLI -ErrorAction SilentlyContinue
    }
    else {
        $env:WENLINT_LARK_CLI = $previousLarkCli
    }
}

exit $wenlintExitCode
