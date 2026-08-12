Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ProjectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..\..")).Path
$PowerShellFiles = @(
    (Join-Path $ProjectRoot "scripts\bootstrap.ps1"),
    (Join-Path $ProjectRoot "scripts\dev.ps1"),
    (Join-Path $ProjectRoot "scripts\demo.ps1")
)

foreach ($Path in $PowerShellFiles) {
    $Tokens = $null
    $Errors = $null
    [System.Management.Automation.Language.Parser]::ParseFile(
        $Path,
        [ref]$Tokens,
        [ref]$Errors
    ) | Out-Null
    if ($Errors.Count -gt 0) {
        $Messages = $Errors | ForEach-Object { $_.Message }
        throw "PowerShell syntax errors in $Path`: $($Messages -join '; ')"
    }
}

$DemoScript = Get-Content -Raw -LiteralPath (Join-Path $ProjectRoot "scripts\demo.ps1")
$RequiredDemoMarkers = @(
    'sqlite+aiosqlite:///./var/demo/demo.db',
    'APP_ENV = "development"',
    'MOCK_PAYMENT_ENABLED = "true"',
    'VITE_API_BASE_URL = $ApiBaseUrl',
    'VITE_API_URL = $ApiBaseUrl',
    'CORS_ORIGINS = (@(',
    'seed-demo',
    '--check-heads',
    '127.0.0.1'
)
foreach ($Marker in $RequiredDemoMarkers) {
    if (-not $DemoScript.Contains($Marker)) {
        throw "Demo launcher is missing the required marker: $Marker"
    }
}
if ($DemoScript.Contains("demo-data.py")) {
    throw "Demo launcher must use the backend seed-demo command as the single source of truth."
}

$CmdLauncher = Get-Content -Raw -LiteralPath (Join-Path $ProjectRoot "Start-Demo.cmd")
foreach ($Marker in @(
    "%~dp0",
    "-ExecutionPolicy Bypass",
    "scripts\demo.ps1",
    "exit /b %DEMO_EXIT%"
)) {
    if (-not $CmdLauncher.Contains($Marker)) {
        throw "Start-Demo.cmd is missing the required marker: $Marker"
    }
}

Write-Host "Demo launcher static checks passed."
