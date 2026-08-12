[CmdletBinding()]
param(
    [switch]$StartupCheck,

    [ValidateRange(1, 65535)]
    [int]$ApiPort = 8000,

    [ValidateRange(1, 65535)]
    [int]$KioskPort = 5173,

    [ValidateRange(1, 65535)]
    [int]$KitchenDisplayPort = 5174,

    [ValidateRange(1, 65535)]
    [int]$AdminPort = 5175
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ProvidedParameters = @{}
foreach ($ParameterName in $PSBoundParameters.Keys) {
    $ProvidedParameters[$ParameterName] = $PSBoundParameters[$ParameterName]
}

$ProjectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$PythonExe = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$AlembicConfigPath = Join-Path $ProjectRoot "apps\edge-api\alembic.ini"
$LocalEnvPath = Join-Path $ProjectRoot ".env"
$NodeModulesPath = Join-Path $ProjectRoot "node_modules"
$ViteCliPath = Join-Path $NodeModulesPath "vite\bin\vite.js"
$ViteCliFromApp = "..\..\node_modules\vite\bin\vite.js"
$LogDirectory = Join-Path $ProjectRoot "var\logs"
$RunId = Get-Date -Format "yyyyMMdd-HHmmss-fff"
$Processes = @()

function Repair-DuplicatePathEnvironmentVariable {
    $EnvironmentVariables = [System.Environment]::GetEnvironmentVariables()
    $PathEntries = @(
        $EnvironmentVariables.GetEnumerator() |
            Where-Object { $_.Key -ieq "PATH" }
    )
    if ($PathEntries.Count -le 1) {
        return
    }

    $PathSegments = @(
        $PathEntries |
            ForEach-Object { [string]$_.Value -split ";" } |
            Where-Object { -not [string]::IsNullOrWhiteSpace($_) } |
            Select-Object -Unique
    )
    foreach ($PathEntry in $PathEntries) {
        [System.Environment]::SetEnvironmentVariable(
            [string]$PathEntry.Key,
            $null,
            [System.EnvironmentVariableTarget]::Process
        )
    }
    [System.Environment]::SetEnvironmentVariable(
        "Path",
        ($PathSegments -join ";"),
        [System.EnvironmentVariableTarget]::Process
    )
}

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

function Get-ConfiguredValue {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name
    )

    $ProcessValue = [System.Environment]::GetEnvironmentVariable(
        $Name,
        [System.EnvironmentVariableTarget]::Process
    )
    if (-not [string]::IsNullOrWhiteSpace($ProcessValue)) {
        return $ProcessValue.Trim()
    }

    if (-not (Test-Path -LiteralPath $LocalEnvPath -PathType Leaf)) {
        return $null
    }

    $Pattern = "^\s*" + [regex]::Escape($Name) + "\s*=(.*)$"
    foreach ($Line in Get-Content -LiteralPath $LocalEnvPath -Encoding utf8) {
        $Match = [regex]::Match(
            $Line,
            $Pattern,
            [System.Text.RegularExpressions.RegexOptions]::IgnoreCase
        )
        if (-not $Match.Success) {
            continue
        }

        $Value = $Match.Groups[1].Value.Trim()
        if ($Value.Length -ge 2) {
            $FirstCharacter = $Value.Substring(0, 1)
            $LastCharacter = $Value.Substring($Value.Length - 1, 1)
            if (
                ($FirstCharacter -eq '"' -and $LastCharacter -eq '"') -or
                ($FirstCharacter -eq "'" -and $LastCharacter -eq "'")
            ) {
                $Value = $Value.Substring(1, $Value.Length - 2)
            }
        }
        return $Value
    }

    return $null
}

function Resolve-DevelopmentPort {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ParameterName,

        [Parameter(Mandatory = $true)]
        [string]$EnvironmentName,

        [Parameter(Mandatory = $true)]
        [int]$ExplicitValue,

        [Parameter(Mandatory = $true)]
        [int]$DefaultValue
    )

    if ($ProvidedParameters.ContainsKey($ParameterName)) {
        return $ExplicitValue
    }

    $ConfiguredValue = Get-ConfiguredValue -Name $EnvironmentName
    if ([string]::IsNullOrWhiteSpace($ConfiguredValue)) {
        return $DefaultValue
    }

    $ParsedValue = 0
    if (
        -not [int]::TryParse($ConfiguredValue, [ref]$ParsedValue) -or
        $ParsedValue -lt 1 -or
        $ParsedValue -gt 65535
    ) {
        throw "$EnvironmentName must be an integer from 1 through 65535. Found: $ConfiguredValue"
    }
    return $ParsedValue
}

function Get-DevelopmentCorsOrigins {
    param(
        [Parameter(Mandatory = $true)]
        [int[]]$FrontendPorts
    )

    $Origins = @()
    $ConfiguredValue = Get-ConfiguredValue -Name "CORS_ORIGINS"
    if (-not [string]::IsNullOrWhiteSpace($ConfiguredValue)) {
        if (-not $ConfiguredValue.TrimStart().StartsWith("[")) {
            throw "CORS_ORIGINS must be a JSON array of HTTP origins."
        }
        try {
            $ConfiguredOrigins = $ConfiguredValue | ConvertFrom-Json -ErrorAction Stop
        }
        catch {
            throw "CORS_ORIGINS must be a JSON array of HTTP origins. $($_.Exception.Message)"
        }
        foreach ($ConfiguredOrigin in $ConfiguredOrigins) {
            $Origins += [string]$ConfiguredOrigin
        }
    }

    foreach ($FrontendPort in $FrontendPorts) {
        $Origins += "http://localhost:$FrontendPort"
        $Origins += "http://127.0.0.1:$FrontendPort"
    }

    $NormalizedOrigins = @(
        $Origins |
            ForEach-Object { ([string]$_).Trim().TrimEnd("/") } |
            Where-Object { -not [string]::IsNullOrWhiteSpace($_) } |
            Select-Object -Unique
    )
    foreach ($Origin in $NormalizedOrigins) {
        $ParsedOrigin = $null
        if (
            -not [uri]::TryCreate($Origin, [System.UriKind]::Absolute, [ref]$ParsedOrigin) -or
            $ParsedOrigin.Scheme -notin @("http", "https") -or
            $ParsedOrigin.AbsolutePath -ne "/" -or
            -not [string]::IsNullOrEmpty($ParsedOrigin.Query) -or
            -not [string]::IsNullOrEmpty($ParsedOrigin.Fragment) -or
            -not [string]::IsNullOrEmpty($ParsedOrigin.UserInfo)
        ) {
            throw "CORS_ORIGINS contains an invalid HTTP origin: $Origin"
        }
    }
    return $NormalizedOrigins
}

function Start-LoggedProcess {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name,

        [Parameter(Mandatory = $true)]
        [string]$FilePath,

        [Parameter(Mandatory = $true)]
        [string[]]$ArgumentList,

        [Parameter(Mandatory = $true)]
        [string]$WorkingDirectory
    )

    $StandardOutputPath = Join-Path $LogDirectory "$Name-$RunId.stdout.log"
    $StandardErrorPath = Join-Path $LogDirectory "$Name-$RunId.stderr.log"
    $Process = Start-Process `
        -FilePath $FilePath `
        -ArgumentList $ArgumentList `
        -WorkingDirectory $WorkingDirectory `
        -WindowStyle Hidden `
        -RedirectStandardOutput $StandardOutputPath `
        -RedirectStandardError $StandardErrorPath `
        -PassThru

    return [pscustomobject]@{
        Name = $Name
        Process = $Process
        StandardOutputPath = $StandardOutputPath
        StandardErrorPath = $StandardErrorPath
    }
}

function Test-TcpPortOpen {
    param(
        [Parameter(Mandatory = $true)]
        [int]$Port
    )

    $Client = [System.Net.Sockets.TcpClient]::new()
    $Connected = $false
    try {
        $ConnectTask = $Client.ConnectAsync("127.0.0.1", $Port)
        if ($ConnectTask.Wait(500)) {
            $Connected = $Client.Connected
        }
    }
    catch {
        $Connected = $false
    }
    finally {
        $Client.Dispose()
    }

    return $Connected
}

function Assert-TcpPortAvailable {
    param(
        [Parameter(Mandatory = $true)]
        [int]$Port
    )

    if (Test-TcpPortOpen -Port $Port) {
        throw "TCP port $Port is already in use. Stop the existing process and run dev.ps1 again."
    }
}

function Write-ProcessLogTail {
    param(
        [Parameter(Mandatory = $true)]
        [pscustomobject]$Entry
    )

    Write-Host "Recent logs for $($Entry.Name):"
    $Lines = @()
    if (Test-Path -LiteralPath $Entry.StandardErrorPath -PathType Leaf) {
        $Lines += Get-Content `
            -LiteralPath $Entry.StandardErrorPath `
            -Encoding utf8 `
            -Tail 30 `
            -ErrorAction SilentlyContinue
    }
    if ($Lines.Count -eq 0 -and (Test-Path -LiteralPath $Entry.StandardOutputPath -PathType Leaf)) {
        $Lines += Get-Content `
            -LiteralPath $Entry.StandardOutputPath `
            -Encoding utf8 `
            -Tail 30 `
            -ErrorAction SilentlyContinue
    }

    if ($Lines.Count -eq 0) {
        Write-Host "  No process output was captured."
    }
    else {
        $Lines | ForEach-Object { Write-Host "  $_" }
    }
}

function Assert-ProcessRunning {
    param(
        [Parameter(Mandatory = $true)]
        [pscustomobject]$Entry
    )

    $Entry.Process.Refresh()
    if ($Entry.Process.HasExited) {
        $Entry.Process.WaitForExit(5000) | Out-Null
        $Entry.Process.Refresh()
        Write-ProcessLogTail -Entry $Entry
        $ExitCode = $Entry.Process.ExitCode
        if ($null -eq $ExitCode -or [string]::IsNullOrWhiteSpace([string]$ExitCode)) {
            $ExitCode = "unknown"
        }
        throw "$($Entry.Name) exited before becoming ready (exit code: $ExitCode)."
    }
}

function Wait-ForHttpEndpoint {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Uri,

        [Parameter(Mandatory = $true)]
        [pscustomobject]$Entry,

        [int]$TimeoutSeconds = 60
    )

    $Deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    while ([DateTime]::UtcNow -lt $Deadline) {
        Assert-ProcessRunning -Entry $Entry

        try {
            $Response = Invoke-WebRequest `
                -Uri $Uri `
                -UseBasicParsing `
                -TimeoutSec 2 `
                -ErrorAction Stop
            if ($Response.StatusCode -eq 200) {
                return
            }
        }
        catch {
            Start-Sleep -Milliseconds 500
        }
    }

    Write-ProcessLogTail -Entry $Entry
    throw "$($Entry.Name) did not become ready within $TimeoutSeconds seconds."
}

function Stop-TrackedProcess {
    param(
        [Parameter(Mandatory = $true)]
        [pscustomobject]$Entry
    )

    try {
        $Entry.Process.Refresh()
        if (-not $Entry.Process.HasExited) {
            Stop-Process -Id $Entry.Process.Id -Force -ErrorAction Stop
            $Entry.Process.WaitForExit(5000) | Out-Null
        }
    }
    catch {
        Write-Warning "Could not stop $($Entry.Name): $($_.Exception.Message)"
    }
}

function Wait-ForPortsReleased {
    param(
        [Parameter(Mandatory = $true)]
        [int[]]$PortList,

        [int]$TimeoutSeconds = 10
    )

    $Deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    do {
        $OpenPorts = @($PortList | Where-Object { Test-TcpPortOpen -Port $_ })
        if ($OpenPorts.Count -eq 0) {
            return
        }
        Start-Sleep -Milliseconds 200
    } while ([DateTime]::UtcNow -lt $Deadline)

    throw "Development process cleanup failed; ports still open: $($OpenPorts -join ', ')."
}

if (-not (Test-Path -LiteralPath $PythonExe -PathType Leaf)) {
    throw "Virtual environment not found. Run .\scripts\bootstrap.ps1 first."
}

if (-not (Test-Path -LiteralPath $AlembicConfigPath -PathType Leaf)) {
    throw "Alembic configuration not found: $AlembicConfigPath"
}

$ApiPort = Resolve-DevelopmentPort `
    -ParameterName "ApiPort" `
    -EnvironmentName "API_PORT" `
    -ExplicitValue $ApiPort `
    -DefaultValue 8000
$KioskPort = Resolve-DevelopmentPort `
    -ParameterName "KioskPort" `
    -EnvironmentName "KIOSK_PORT" `
    -ExplicitValue $KioskPort `
    -DefaultValue 5173
$KitchenDisplayPort = Resolve-DevelopmentPort `
    -ParameterName "KitchenDisplayPort" `
    -EnvironmentName "KITCHEN_DISPLAY_PORT" `
    -ExplicitValue $KitchenDisplayPort `
    -DefaultValue 5174
$AdminPort = Resolve-DevelopmentPort `
    -ParameterName "AdminPort" `
    -EnvironmentName "ADMIN_PORT" `
    -ExplicitValue $AdminPort `
    -DefaultValue 5175

$FrontendPorts = @($KioskPort, $KitchenDisplayPort, $AdminPort)
$Ports = @($ApiPort) + $FrontendPorts
if (@($Ports | Select-Object -Unique).Count -ne $Ports.Count) {
    throw "API_PORT, KIOSK_PORT, KITCHEN_DISPLAY_PORT, and ADMIN_PORT must be unique."
}

Repair-DuplicatePathEnvironmentVariable

$NodeCommand = Get-Command -Name "node.exe" -CommandType Application -ErrorAction SilentlyContinue
if ($null -eq $NodeCommand) {
    throw "node.exe was not found. Run .\scripts\bootstrap.ps1 after installing Node.js 24."
}

if (-not (Test-Path -LiteralPath $ViteCliPath -PathType Leaf)) {
    throw "Vite was not found in node_modules. Run .\scripts\bootstrap.ps1 first."
}

foreach ($Port in $Ports) {
    Assert-TcpPortAvailable -Port $Port
}

$DevelopmentCorsOrigins = Get-DevelopmentCorsOrigins -FrontendPorts $FrontendPorts
$RuntimeEnvironmentVariables = [ordered]@{
    SMART_DRINK_ENV_FILE = $LocalEnvPath
    PYTHONUTF8 = "1"
    API_HOST = "127.0.0.1"
    API_PORT = $ApiPort.ToString()
    KIOSK_PORT = $KioskPort.ToString()
    KITCHEN_DISPLAY_PORT = $KitchenDisplayPort.ToString()
    ADMIN_PORT = $AdminPort.ToString()
    CORS_ORIGINS = ConvertTo-Json -InputObject @($DevelopmentCorsOrigins) -Compress
}
$PreviousRuntimeEnvironment = @{}
foreach ($Name in $RuntimeEnvironmentVariables.Keys) {
    $PreviousRuntimeEnvironment[$Name] = [System.Environment]::GetEnvironmentVariable(
        $Name,
        [System.EnvironmentVariableTarget]::Process
    )
    [System.Environment]::SetEnvironmentVariable(
        $Name,
        [string]$RuntimeEnvironmentVariables[$Name],
        [System.EnvironmentVariableTarget]::Process
    )
}

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

    New-Item -ItemType Directory -Path $LogDirectory -Force | Out-Null

    try {
        $Processes += Start-LoggedProcess `
            -Name "edge-api" `
            -FilePath $PythonExe `
            -ArgumentList @(
                "-m",
                "uvicorn",
                "app.main:app",
                "--app-dir",
                "apps\edge-api",
                "--host",
                "127.0.0.1",
                "--port",
                $ApiPort.ToString(),
                "--no-access-log"
            ) `
            -WorkingDirectory $ProjectRoot

        $Processes += Start-LoggedProcess `
            -Name "kiosk" `
            -FilePath $NodeCommand.Source `
            -ArgumentList @(
                $ViteCliFromApp,
                "--host",
                "127.0.0.1",
                "--port",
                $KioskPort.ToString(),
                "--strictPort"
            ) `
            -WorkingDirectory (Join-Path $ProjectRoot "apps\kiosk-web")

        $Processes += Start-LoggedProcess `
            -Name "kitchen-display" `
            -FilePath $NodeCommand.Source `
            -ArgumentList @(
                $ViteCliFromApp,
                "--host",
                "127.0.0.1",
                "--port",
                $KitchenDisplayPort.ToString(),
                "--strictPort"
            ) `
            -WorkingDirectory (Join-Path $ProjectRoot "apps\kitchen-display-web")

        $Processes += Start-LoggedProcess `
            -Name "admin" `
            -FilePath $NodeCommand.Source `
            -ArgumentList @(
                $ViteCliFromApp,
                "--host",
                "127.0.0.1",
                "--port",
                $AdminPort.ToString(),
                "--strictPort"
            ) `
            -WorkingDirectory (Join-Path $ProjectRoot "apps\admin-web")

        Wait-ForHttpEndpoint `
            -Uri "http://127.0.0.1:$ApiPort/api/v1/health/ready" `
            -Entry ($Processes | Where-Object Name -eq "edge-api")
        Wait-ForHttpEndpoint `
            -Uri "http://127.0.0.1:$KioskPort" `
            -Entry ($Processes | Where-Object Name -eq "kiosk")
        Wait-ForHttpEndpoint `
            -Uri "http://127.0.0.1:$KitchenDisplayPort" `
            -Entry ($Processes | Where-Object Name -eq "kitchen-display")
        Wait-ForHttpEndpoint `
            -Uri "http://127.0.0.1:$AdminPort" `
            -Entry ($Processes | Where-Object Name -eq "admin")

        Write-Host "All development services are ready."
        Write-Host "Kiosk:           http://127.0.0.1:$KioskPort"
        Write-Host "Kitchen Display: http://127.0.0.1:$KitchenDisplayPort"
        Write-Host "Admin:           http://127.0.0.1:$AdminPort"
        Write-Host "API docs:        http://127.0.0.1:$ApiPort/docs"
        Write-Host "Logs:            $LogDirectory"

        if ($StartupCheck) {
            Write-Host "Startup check passed; stopping development services."
        }
        else {
            Write-Host "Press Ctrl+C to stop all processes."

            while ($true) {
                foreach ($Entry in $Processes) {
                    Assert-ProcessRunning -Entry $Entry
                }
                Start-Sleep -Seconds 1
            }
        }
    }
    finally {
        foreach ($Entry in $Processes) {
            Stop-TrackedProcess -Entry $Entry
        }
        Wait-ForPortsReleased -PortList $Ports
    }

    if ($StartupCheck) {
        Write-Host "Startup and cleanup checks passed."
    }
}
finally {
    foreach ($Name in $RuntimeEnvironmentVariables.Keys) {
        [System.Environment]::SetEnvironmentVariable(
            $Name,
            $PreviousRuntimeEnvironment[$Name],
            [System.EnvironmentVariableTarget]::Process
        )
    }
}
