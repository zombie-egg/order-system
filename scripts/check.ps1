[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ProjectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$PythonExe = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

function Invoke-NativeCommand {
    param(
        [Parameter(Mandatory = $true)]
        [string]$FilePath,

        [string[]]$ArgumentList = @(),

        [Parameter(Mandatory = $true)]
        [string]$FailureMessage
    )

    & $FilePath @ArgumentList
    if ($LASTEXITCODE -ne 0) {
        throw "$FailureMessage Exit code: $LASTEXITCODE."
    }
}

if (-not (Test-Path -LiteralPath $PythonExe -PathType Leaf)) {
    throw "Virtual environment not found. Run .\scripts\bootstrap.ps1 first."
}

$NpmCommand = Get-Command -Name "npm.cmd" -CommandType Application -ErrorAction SilentlyContinue
if ($null -eq $NpmCommand) {
    throw "npm.cmd was not found. Run .\scripts\bootstrap.ps1 after installing Node.js 24."
}

Push-Location $ProjectRoot
try {
    Write-Host "Checking Python formatting..."
    Invoke-NativeCommand `
        -FilePath $PythonExe `
        -ArgumentList @("-m", "ruff", "format", "--check", "apps\edge-api") `
        -FailureMessage "Python format check failed."

    Write-Host "Checking Python lint rules..."
    Invoke-NativeCommand `
        -FilePath $PythonExe `
        -ArgumentList @("-m", "ruff", "check", "apps\edge-api") `
        -FailureMessage "Python lint failed."

    Write-Host "Checking Python types..."
    Invoke-NativeCommand `
        -FilePath $PythonExe `
        -ArgumentList @(
            "-m",
            "mypy",
            "apps\edge-api\app",
            "apps\edge-api\migrations",
            "apps\edge-api\tests"
        ) `
        -FailureMessage "Python type checking failed."

    Write-Host "Running Python tests..."
    Invoke-NativeCommand `
        -FilePath $PythonExe `
        -ArgumentList @("-m", "pytest", "apps\edge-api\tests") `
        -FailureMessage "Python tests failed."

    Write-Host "Running frontend checks..."
    Invoke-NativeCommand `
        -FilePath $NpmCommand.Source `
        -ArgumentList @("run", "check:frontend") `
        -FailureMessage "Frontend checks failed."
}
finally {
    Pop-Location
}

Write-Host "All project checks passed."
