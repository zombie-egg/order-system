[CmdletBinding()]
param(
    [switch]$StartupCheck,

    [switch]$NoBrowser,

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
$ProvidedParameters = @{}
foreach ($ParameterName in $PSBoundParameters.Keys) {
    $ProvidedParameters[$ParameterName] = $PSBoundParameters[$ParameterName]
}

$PythonExe = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$BootstrapScript = Join-Path $PSScriptRoot "bootstrap.ps1"
$DevScript = Join-Path $PSScriptRoot "dev.ps1"
$LocalEnvPath = Join-Path $ProjectRoot ".env"
$AlembicConfigPath = Join-Path $ProjectRoot "apps\edge-api\alembic.ini"
$ViteCliPath = Join-Path $ProjectRoot "node_modules\vite\bin\vite.js"
$DemoDirectory = Join-Path $ProjectRoot "var\demo"
$DemoDatabasePath = Join-Path $DemoDirectory "demo.db"
$DemoDatabaseUrl = "sqlite+aiosqlite:///./var/demo/demo.db"
$BrowserLauncher = $null

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

function Test-ProjectRuntimeReady {
    if (-not (Test-Path -LiteralPath $PythonExe -PathType Leaf)) {
        return $false
    }

    $NodeCommand = Get-Command -Name "node.exe" -CommandType Application -ErrorAction SilentlyContinue
    if ($null -eq $NodeCommand) {
        return $false
    }
    if (-not (Test-Path -LiteralPath $ViteCliPath -PathType Leaf)) {
        return $false
    }

    $PreviousErrorPreference = $ErrorActionPreference
    $PreviousPythonPath = [System.Environment]::GetEnvironmentVariable(
        "PYTHONPATH",
        [System.EnvironmentVariableTarget]::Process
    )
    try {
        $ErrorActionPreference = "Continue"
        [System.Environment]::SetEnvironmentVariable(
            "PYTHONPATH",
            (Join-Path $ProjectRoot "apps\edge-api"),
            [System.EnvironmentVariableTarget]::Process
        )
        & $PythonExe -c "import alembic, argon2, jwt, uvicorn, app.cli" *> $null
        if ($LASTEXITCODE -ne 0) {
            return $false
        }

        & $NodeCommand.Source -e `
            "process.exit(Number(process.versions.node.split('.')[0]) === 24 ? 0 : 1)" *> $null
        if ($LASTEXITCODE -ne 0) {
            return $false
        }

        return $true
    }
    finally {
        [System.Environment]::SetEnvironmentVariable(
            "PYTHONPATH",
            $PreviousPythonPath,
            [System.EnvironmentVariableTarget]::Process
        )
        $ErrorActionPreference = $PreviousErrorPreference
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

function Resolve-DemoPort {
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

function Test-DemoTcpPortOpen {
    param(
        [Parameter(Mandatory = $true)]
        [ValidateRange(1, 65535)]
        [int]$Port
    )

    $Client = [System.Net.Sockets.TcpClient]::new()
    try {
        $Connection = $Client.BeginConnect("127.0.0.1", $Port, $null, $null)
        if (-not $Connection.AsyncWaitHandle.WaitOne(250)) {
            return $false
        }
        $Client.EndConnect($Connection)
        return $true
    }
    catch {
        return $false
    }
    finally {
        $Client.Dispose()
    }
}

function Resolve-AvailableDemoPort {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ParameterName,

        [Parameter(Mandatory = $true)]
        [ValidateRange(1, 65535)]
        [int]$PreferredPort,

        [Parameter(Mandatory = $true)]
        [ValidateRange(1, 65535)]
        [int]$FallbackStart,

        [int[]]$ReservedPorts = @()
    )

    if (
        $ReservedPorts -notcontains $PreferredPort -and
        -not (Test-DemoTcpPortOpen -Port $PreferredPort)
    ) {
        return $PreferredPort
    }

    if ($ProvidedParameters.ContainsKey($ParameterName)) {
        throw "TCP port $PreferredPort requested by -$ParameterName is already in use."
    }

    $FallbackEnd = [Math]::Min($FallbackStart + 99, 65535)
    for ($Candidate = $FallbackStart; $Candidate -le $FallbackEnd; $Candidate++) {
        if (
            $ReservedPorts -notcontains $Candidate -and
            -not (Test-DemoTcpPortOpen -Port $Candidate)
        ) {
            Write-Warning (
                "TCP port $PreferredPort is already in use. " +
                "The demo will automatically use port $Candidate instead."
            )
            return $Candidate
        }
    }

    throw (
        "TCP port $PreferredPort is already in use and no free fallback port was found " +
        "from $FallbackStart through $FallbackEnd."
    )
}

function Get-DemoSeedResult {
    $Output = & $PythonExe -m app.cli seed-demo
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to initialize the local demo data. Exit code: $LASTEXITCODE."
    }

    try {
        $Result = ($Output -join [System.Environment]::NewLine) |
            ConvertFrom-Json -ErrorAction Stop
    }
    catch {
        throw "The demo seed command returned invalid JSON. $($_.Exception.Message)"
    }

    $RequiredProperties = @(
        "created",
        "tenant_code",
        "owner_username",
        "owner_password",
        "kiosk_id",
        "kiosk_key",
        "fulfillment_endpoint_id",
        "fulfillment_endpoint_key",
        "product_count"
    )
    foreach ($PropertyName in $RequiredProperties) {
        $Property = $Result.PSObject.Properties[$PropertyName]
        if (
            $null -eq $Property -or
            (
                $PropertyName -ne "created" -and
                [string]::IsNullOrWhiteSpace([string]$Property.Value)
            )
        ) {
            throw "The demo seed result is missing '$PropertyName'."
        }
    }
    return $Result
}

function Write-DemoInstructions {
    param(
        [Parameter(Mandatory = $true)]
        [pscustomobject]$Credentials
    )

    $SeedAction = if ([bool]$Credentials.created) { "created" } else { "verified" }
    Write-Host ""
    Write-Host "============================================================" -ForegroundColor Cyan
    Write-Host " SipPilot local demo is ready ($SeedAction)." -ForegroundColor Cyan
    Write-Host "============================================================" -ForegroundColor Cyan
    Write-Host "Start with Kitchen Display and keep that page connected."
    Write-Host ""
    Write-Host "1. Kitchen Display: $KitchenDisplayUrl"
    Write-Host "   API:       $ApiBaseUrl"
    Write-Host "   Endpoint:  $($Credentials.fulfillment_endpoint_id)"
    Write-Host "   Key:       $($Credentials.fulfillment_endpoint_key)"
    Write-Host "   Tenant:    $($Credentials.tenant_code)"
    Write-Host "   Username:  $($Credentials.owner_username)"
    Write-Host "   Password:  $($Credentials.owner_password)"
    Write-Host ""
    Write-Host "2. Kiosk:           $KioskUrl"
    Write-Host "   API:       $ApiBaseUrl"
    Write-Host "   Kiosk ID:  $($Credentials.kiosk_id)"
    Write-Host "   Key:       $($Credentials.kiosk_key)"
    Write-Host ""
    Write-Host "3. Admin:           $AdminUrl"
    Write-Host "   API:       $ApiBaseUrl"
    Write-Host "   Tenant:    $($Credentials.tenant_code)"
    Write-Host "   Username:  $($Credentials.owner_username)"
    Write-Host "   Password:  $($Credentials.owner_password)"
    Write-Host ""
    Write-Host "Products:         $($Credentials.product_count)"
    Write-Host "Demo database:    $DemoDatabasePath"
    Write-Host "API documentation: http://127.0.0.1:$ApiPort/docs"
    Write-Host ""
    Write-Host "Local mock payment only. Never use these demo credentials in production." `
        -ForegroundColor Yellow
    Write-Host "Press Ctrl+C in this window to stop every service."
    Write-Host "============================================================" -ForegroundColor Cyan
    Write-Host ""
}

if (-not (Test-Path -LiteralPath $BootstrapScript -PathType Leaf)) {
    throw "Bootstrap script not found: $BootstrapScript"
}
if (-not (Test-Path -LiteralPath $DevScript -PathType Leaf)) {
    throw "Development launcher not found: $DevScript"
}
if (-not (Test-Path -LiteralPath $AlembicConfigPath -PathType Leaf)) {
    throw "Alembic configuration not found: $AlembicConfigPath"
}

$ApiPort = Resolve-DemoPort `
    -ParameterName "ApiPort" `
    -EnvironmentName "API_PORT" `
    -ExplicitValue $ApiPort `
    -DefaultValue 8000
$KioskPort = Resolve-DemoPort `
    -ParameterName "KioskPort" `
    -EnvironmentName "KIOSK_PORT" `
    -ExplicitValue $KioskPort `
    -DefaultValue 5173
$KitchenDisplayPort = Resolve-DemoPort `
    -ParameterName "KitchenDisplayPort" `
    -EnvironmentName "KITCHEN_DISPLAY_PORT" `
    -ExplicitValue $KitchenDisplayPort `
    -DefaultValue 5174
$AdminPort = Resolve-DemoPort `
    -ParameterName "AdminPort" `
    -EnvironmentName "ADMIN_PORT" `
    -ExplicitValue $AdminPort `
    -DefaultValue 5175

$ReservedDemoPorts = @()
$ApiPort = Resolve-AvailableDemoPort `
    -ParameterName "ApiPort" `
    -PreferredPort $ApiPort `
    -FallbackStart 18000 `
    -ReservedPorts $ReservedDemoPorts
$ReservedDemoPorts += $ApiPort
$KioskPort = Resolve-AvailableDemoPort `
    -ParameterName "KioskPort" `
    -PreferredPort $KioskPort `
    -FallbackStart 15173 `
    -ReservedPorts $ReservedDemoPorts
$ReservedDemoPorts += $KioskPort
$KitchenDisplayPort = Resolve-AvailableDemoPort `
    -ParameterName "KitchenDisplayPort" `
    -PreferredPort $KitchenDisplayPort `
    -FallbackStart 15174 `
    -ReservedPorts $ReservedDemoPorts
$ReservedDemoPorts += $KitchenDisplayPort
$AdminPort = Resolve-AvailableDemoPort `
    -ParameterName "AdminPort" `
    -PreferredPort $AdminPort `
    -FallbackStart 15175 `
    -ReservedPorts $ReservedDemoPorts

$ResolvedPorts = @($ApiPort, $KioskPort, $KitchenDisplayPort, $AdminPort)
if (@($ResolvedPorts | Select-Object -Unique).Count -ne $ResolvedPorts.Count) {
    throw "API_PORT, KIOSK_PORT, KITCHEN_DISPLAY_PORT, and ADMIN_PORT must be unique."
}

$ApiBaseUrl = "http://127.0.0.1:$ApiPort/api/v1"
$KioskUrl = "http://127.0.0.1:$KioskPort"
$KitchenDisplayUrl = "http://127.0.0.1:$KitchenDisplayPort"
$AdminUrl = "http://127.0.0.1:$AdminPort"

$RuntimeEnvironmentVariables = [ordered]@{
    SMART_DRINK_ENV_FILE = $LocalEnvPath
    APP_ENV = "development"
    DATABASE_URL = $DemoDatabaseUrl
    JWT_SECRET = "local-demo-only-smart-drink-jwt-secret-2026"
    MOCK_PAYMENT_ENABLED = "true"
    MOCK_PAYMENT_SCENARIO = "APPROVED"
    VITE_API_BASE_URL = $ApiBaseUrl
    VITE_API_URL = $ApiBaseUrl
    CORS_ORIGINS = (@(
        "http://localhost:$KioskPort",
        "http://localhost:$KitchenDisplayPort",
        "http://localhost:$AdminPort",
        "http://127.0.0.1:$KioskPort",
        "http://127.0.0.1:$KitchenDisplayPort",
        "http://127.0.0.1:$AdminPort"
    ) | ConvertTo-Json -Compress)
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
    New-Item -ItemType Directory -Path $DemoDirectory -Force | Out-Null

    if (-not (Test-ProjectRuntimeReady)) {
        Write-Host "Installing or repairing local project dependencies..." -ForegroundColor Yellow
        try {
            & $BootstrapScript
        }
        catch {
            throw (
                "Project bootstrap failed. Check Python 3.12/3.13, Node.js 24, " +
                "PyPI/npm access, then rerun Start-Demo.cmd. $($_.Exception.Message)"
            )
        }
    }
    if (-not (Test-ProjectRuntimeReady)) {
        throw "Project dependencies are incomplete. Run .\scripts\bootstrap.ps1 and retry."
    }

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
            -FailureMessage "Failed to upgrade the dedicated demo database schema."

        Invoke-NativeCommand `
            -FilePath $PythonExe `
            -ArgumentList @(
                "-m",
                "alembic",
                "-c",
                $AlembicConfigPath,
                "current",
                "--check-heads"
            ) `
            -FailureMessage "The dedicated demo database is not at the Alembic head revision."

        $Credentials = Get-DemoSeedResult
    }
    finally {
        Pop-Location
    }

    Write-DemoInstructions -Credentials $Credentials

    $BrowserJobAvailable = $null -ne (
        Get-Command -Name "Start-Job" -CommandType Cmdlet -ErrorAction SilentlyContinue
    )
    if (-not $NoBrowser -and -not $StartupCheck -and -not $BrowserJobAvailable) {
        Write-Warning "Automatic browser launch is unavailable. Open the printed URLs manually."
    }

    $DevArguments = @{
        ApiPort = $ApiPort
        KioskPort = $KioskPort
        KitchenDisplayPort = $KitchenDisplayPort
        AdminPort = $AdminPort
    }
    if ($StartupCheck) {
        $DevArguments["StartupCheck"] = $true
    }

    if (-not $NoBrowser -and -not $StartupCheck -and $BrowserJobAvailable) {
        $BrowserLauncher = Start-Job -ScriptBlock {
            param(
                [string]$KitchenUrl,
                [string]$KioskPageUrl,
                [string]$AdminPageUrl
            )

            $Deadline = [DateTime]::UtcNow.AddSeconds(120)
            while ([DateTime]::UtcNow -lt $Deadline) {
                try {
                    $Response = Invoke-WebRequest `
                        -Uri $KitchenUrl `
                        -UseBasicParsing `
                        -TimeoutSec 2 `
                        -ErrorAction Stop
                    if ($Response.StatusCode -eq 200) {
                        Start-Process -FilePath $KitchenUrl
                        Start-Process -FilePath $KioskPageUrl
                        Start-Process -FilePath $AdminPageUrl
                        return
                    }
                }
                catch {
                    Start-Sleep -Milliseconds 500
                }
            }
        } -ArgumentList $KitchenDisplayUrl, $KioskUrl, $AdminUrl
    }

    try {
        & $DevScript @DevArguments
        if (-not $?) {
            throw "Development services failed to start."
        }
    }
    finally {
        if ($null -ne $BrowserLauncher) {
            Remove-Job -Job $BrowserLauncher -Force -ErrorAction SilentlyContinue
        }
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
