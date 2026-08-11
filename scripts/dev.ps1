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

$ProjectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$PythonExe = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$NodeModulesPath = Join-Path $ProjectRoot "node_modules"
$ViteCliPath = Join-Path $NodeModulesPath "vite\bin\vite.js"
$ViteCliFromApp = "..\..\node_modules\vite\bin\vite.js"
$LogDirectory = Join-Path $ProjectRoot "var\logs"
$RunId = Get-Date -Format "yyyyMMdd-HHmmss-fff"
$Processes = @()
$Ports = @($ApiPort, $KioskPort, $KitchenDisplayPort, $AdminPort)

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
        Write-ProcessLogTail -Entry $Entry
        throw "$($Entry.Name) exited with code $($Entry.Process.ExitCode)."
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
            $ApiPort.ToString()
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
}

if ($StartupCheck) {
    Wait-ForPortsReleased -PortList $Ports
    Write-Host "Startup and cleanup checks passed."
}
