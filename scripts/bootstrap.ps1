[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ProjectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$VirtualEnvPath = Join-Path $ProjectRoot ".venv"
$PythonExe = Join-Path $VirtualEnvPath "Scripts\python.exe"
$EdgeApiPath = Join-Path $ProjectRoot "apps\edge-api"
$AlembicConfigPath = Join-Path $EdgeApiPath "alembic.ini"
$LocalEnvPath = Join-Path $ProjectRoot ".env"
$ExampleEnvPath = Join-Path $ProjectRoot ".env.example"
$PackageLockPath = Join-Path $ProjectRoot "package-lock.json"
$RuntimePath = Join-Path $ProjectRoot "var"
$LogPath = Join-Path $RuntimePath "logs"

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

function Get-CompatiblePythonLauncher {
    $Candidates = @()
    $PyLauncher = Get-Command -Name "py.exe" -CommandType Application -ErrorAction SilentlyContinue
    $PythonCommand = Get-Command -Name "python.exe" -CommandType Application -ErrorAction SilentlyContinue

    if ($null -ne $PyLauncher) {
        $Candidates += [pscustomobject]@{
            FilePath = $PyLauncher.Source
            PrefixArguments = @("-3.12")
        }
        $Candidates += [pscustomobject]@{
            FilePath = $PyLauncher.Source
            PrefixArguments = @("-3.13")
        }
    }

    if ($null -ne $PythonCommand) {
        $Candidates += [pscustomobject]@{
            FilePath = $PythonCommand.Source
            PrefixArguments = @()
        }
    }

    foreach ($Candidate in $Candidates) {
        $VersionResult = & $Candidate.FilePath @($Candidate.PrefixArguments) -c `
            "import sys; print('compatible' if (3, 12) <= sys.version_info[:2] < (3, 14) else 'unsupported')" `
            2>$null

        if ($LASTEXITCODE -eq 0 -and $VersionResult -contains "compatible") {
            return $Candidate
        }
    }

    throw "Python 3.12 or 3.13 was not found. Install Python 3.12 and run this script again."
}

if (-not (Test-Path -LiteralPath $ExampleEnvPath -PathType Leaf)) {
    throw "Missing environment template: $ExampleEnvPath"
}

if (-not (Test-Path -LiteralPath $LocalEnvPath -PathType Leaf)) {
    Copy-Item -LiteralPath $ExampleEnvPath -Destination $LocalEnvPath
    Write-Host "Created local environment file: $LocalEnvPath"
}

if (-not (Test-Path -LiteralPath $PythonExe -PathType Leaf)) {
    $PythonLauncher = Get-CompatiblePythonLauncher
    $VenvArguments = @($PythonLauncher.PrefixArguments) + @("-m", "venv", $VirtualEnvPath)
    Invoke-NativeCommand `
        -FilePath $PythonLauncher.FilePath `
        -ArgumentList $VenvArguments `
        -FailureMessage "Failed to create the Python virtual environment."
}

Invoke-NativeCommand `
    -FilePath $PythonExe `
    -ArgumentList @(
        "-c",
        "import sys; raise SystemExit(0 if (3, 12) <= sys.version_info[:2] < (3, 14) else 1)"
    ) `
    -FailureMessage "The virtual environment must use Python 3.12 or 3.13. Remove .venv and bootstrap again."

Invoke-NativeCommand `
    -FilePath $PythonExe `
    -ArgumentList @(
        "-m",
        "pip",
        "install",
        "--disable-pip-version-check",
        "--no-input",
        "--upgrade",
        "pip"
    ) `
    -FailureMessage "Failed to upgrade pip."

$EditableRequirement = "${EdgeApiPath}[dev]"
Invoke-NativeCommand `
    -FilePath $PythonExe `
    -ArgumentList @(
        "-m",
        "pip",
        "install",
        "--disable-pip-version-check",
        "--no-input",
        "--editable",
        $EditableRequirement
    ) `
    -FailureMessage "Failed to install Python dependencies."

New-Item -ItemType Directory -Path $RuntimePath -Force | Out-Null

$PreviousSettingsEnvFile = [System.Environment]::GetEnvironmentVariable(
    "SMART_DRINK_ENV_FILE",
    [System.EnvironmentVariableTarget]::Process
)
[System.Environment]::SetEnvironmentVariable(
    "SMART_DRINK_ENV_FILE",
    $LocalEnvPath,
    [System.EnvironmentVariableTarget]::Process
)
try {
    Push-Location $ProjectRoot
    try {
        Invoke-NativeCommand `
            -FilePath $PythonExe `
            -ArgumentList @(
                "-m",
                "alembic",
                "-c",
                $AlembicConfigPath,
                "upgrade",
                "head"
            ) `
            -FailureMessage "Failed to upgrade the local database schema."
    }
    finally {
        Pop-Location
    }
}
finally {
    [System.Environment]::SetEnvironmentVariable(
        "SMART_DRINK_ENV_FILE",
        $PreviousSettingsEnvFile,
        [System.EnvironmentVariableTarget]::Process
    )
}

$NodeCommand = Get-Command -Name "node.exe" -CommandType Application -ErrorAction SilentlyContinue
if ($null -eq $NodeCommand) {
    throw "Node.js was not found. Install Node.js 24 and run this script again."
}

Invoke-NativeCommand `
    -FilePath $NodeCommand.Source `
    -ArgumentList @(
        "-e",
        "const major = Number(process.versions.node.split('.')[0]); process.exit(major === 24 ? 0 : 1);"
    ) `
    -FailureMessage "Node.js 24 is required."

$NpmCommand = Get-Command -Name "npm.cmd" -CommandType Application -ErrorAction SilentlyContinue
if ($null -eq $NpmCommand) {
    throw "npm.cmd was not found. Reinstall Node.js 24 and run this script again."
}

$NpmVersion = (& $NpmCommand.Source "--version").Trim()
if ($LASTEXITCODE -ne 0 -or $NpmVersion -notmatch "^11\.") {
    throw "npm 11 is required. Found: $NpmVersion"
}

Push-Location $ProjectRoot
try {
    $NpmArguments = if (Test-Path -LiteralPath $PackageLockPath -PathType Leaf) {
        @("ci")
    }
    else {
        @("install")
    }

    Invoke-NativeCommand `
        -FilePath $NpmCommand.Source `
        -ArgumentList $NpmArguments `
        -FailureMessage "Failed to install npm dependencies."
}
finally {
    Pop-Location
}

New-Item -ItemType Directory -Path $LogPath -Force | Out-Null

Write-Host "Bootstrap complete for: $ProjectRoot"
Write-Host "Run .\scripts\dev.ps1 from the project root to start the project."
