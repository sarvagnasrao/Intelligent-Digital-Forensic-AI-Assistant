# Shared helpers for the IDFA launcher scripts.
#
# Dot-source this file from setup/start/stop. It contains only functions and
# paths, so sourcing it has no side effects. Windows PowerShell 5.1 compatible.

$script:ProjectDir = Split-Path $PSScriptRoot -Parent
$script:VenvDir = Join-Path $script:ProjectDir ".venv"
$script:VenvPython = Join-Path $script:VenvDir "Scripts\python.exe"
$script:PackagesDir = Join-Path $script:ProjectDir "packages"
$script:ToolsDir = Join-Path $script:ProjectDir "tools"
$script:QdrantExe = Join-Path $script:ToolsDir "qdrant\qdrant.exe"
$script:BundledOllamaExe = Join-Path $script:ToolsDir "ollama\ollama.exe"
$script:RunDir = Join-Path $env:LOCALAPPDATA "IDFA\run"
$script:ConfigFile = Join-Path $env:APPDATA "IDFA\config.yaml"

function Write-Step([string]$Message) {
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Write-Ok([string]$Message) {
    Write-Host "  ok   $Message" -ForegroundColor Green
}

function Write-Warn([string]$Message) {
    Write-Host "  warn $Message" -ForegroundColor Yellow
}

function Write-Fail([string]$Message) {
    Write-Host "  fail $Message" -ForegroundColor Red
}

function Write-Info([string]$Message) {
    Write-Host "  info $Message" -ForegroundColor Gray
}

function Test-HttpOk([string]$Url, [int]$TimeoutSec = 3) {
    try {
        $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec $TimeoutSec -ErrorAction Stop
        return ($response.StatusCode -ge 200 -and $response.StatusCode -lt 400)
    } catch {
        return $false
    }
}

function Get-Json([string]$Url, [int]$TimeoutSec = 5) {
    try {
        return Invoke-RestMethod -Uri $Url -TimeoutSec $TimeoutSec -ErrorAction Stop
    } catch {
        return $null
    }
}

function Get-RemoteFile([string]$Url, [string]$Destination) {
    # Invoke-WebRequest buffers the whole response in memory, which stalls on
    # installation media of several hundred megabytes. curl.exe ships with
    # Windows 10 1803+ and streams to disk, so it is preferred when present.
    $parent = Split-Path $Destination -Parent
    if ($parent -and -not (Test-Path $parent)) {
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }

    if (Get-Command curl.exe -ErrorAction SilentlyContinue) {
        & curl.exe -L --fail --retry 3 --retry-delay 3 --connect-timeout 30 `
            -o $Destination $Url
        return ($LASTEXITCODE -eq 0)
    }

    try {
        Invoke-WebRequest -Uri $Url -OutFile $Destination -UseBasicParsing
        return $true
    } catch {
        return $false
    }
}

function Get-PortOwner([int]$Port) {
    try {
        $connection = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction Stop |
            Select-Object -First 1
    } catch {
        return $null
    }
    if (-not $connection) { return $null }
    try {
        return Get-Process -Id $connection.OwningProcess -ErrorAction Stop
    } catch {
        return $null
    }
}

function Format-Process($Process) {
    if (-not $Process) { return "unknown process" }
    $path = ""
    try { $path = $Process.Path } catch { $path = "" }
    if ($path) { return "$($Process.ProcessName) (pid $($Process.Id), $path)" }
    return "$($Process.ProcessName) (pid $($Process.Id))"
}

function Get-ProcessCommandLine([int]$ProcessId) {
    # The executable path of a venv interpreter can resolve to the base
    # installation, so the command line is the reliable way to recognise a
    # process this launcher started.
    try {
        $info = Get-CimInstance Win32_Process -Filter "ProcessId = $ProcessId" -ErrorAction Stop
        if ($info -and $info.CommandLine) { return [string]$info.CommandLine }
    } catch {
        return ""
    }
    return ""
}

function Get-OwnedProcess([int]$ProcessId, [string]$ExpectedName, [string]$PathPart, [string]$CommandPattern) {
    $process = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
    if (-not $process) { return $null }
    if ($ExpectedName -and $process.ProcessName -notlike "*$ExpectedName*") {
        return $null
    }
    if (-not $PathPart -and -not $CommandPattern) { return $process }

    if ($PathPart) {
        $path = ""
        try { $path = $process.Path } catch { $path = "" }
        if ($path -and ($path -like "*$PathPart*")) { return $process }
    }
    if ($CommandPattern) {
        $commandLine = Get-ProcessCommandLine $ProcessId
        if ($commandLine -and ($commandLine -like "*$CommandPattern*")) { return $process }
    }
    return $null
}

function Save-PidFile([string]$Name, [int]$ProcessId) {
    if (-not (Test-Path $RunDir)) {
        New-Item -ItemType Directory -Path $RunDir -Force | Out-Null
    }
    Set-Content -Path (Join-Path $RunDir "$Name.pid") -Value $ProcessId -Encoding ASCII
}

function Read-PidFile([string]$Name) {
    $file = Join-Path $RunDir "$Name.pid"
    if (-not (Test-Path $file)) { return $null }
    $text = (Get-Content -Path $file -ErrorAction SilentlyContinue | Select-Object -First 1)
    if (-not $text) { return $null }
    $number = 0
    if (-not [int]::TryParse($text.Trim(), [ref]$number)) { return $null }
    return $number
}

function Remove-PidFile([string]$Name) {
    $file = Join-Path $RunDir "$Name.pid"
    if (Test-Path $file) { Remove-Item $file -Force -ErrorAction SilentlyContinue }
}

function Stop-ManagedProcess([string]$Name, [string]$ExpectedName, [string]$PathPart, [string]$CommandPattern) {
    $processId = Read-PidFile $Name
    if ($null -eq $processId) { return $false }

    $process = Get-OwnedProcess $processId $ExpectedName $PathPart $CommandPattern
    if (-not $process) {
        Write-Host "  $Name is not running (stale pid file removed)." -ForegroundColor Gray
        Remove-PidFile $Name
        return $false
    }

    Write-Host "Stopping $Name ($(Format-Process $process))..."
    try {
        Stop-Process -Id $process.Id -Force -ErrorAction Stop
    } catch {
        Write-Warn "Could not stop $Name (pid $($process.Id)): $($_.Exception.Message)"
        return $false
    }
    for ($attempt = 0; $attempt -lt 20; $attempt++) {
        if (-not (Get-Process -Id $process.Id -ErrorAction SilentlyContinue)) { break }
        Start-Sleep -Milliseconds 250
    }
    Remove-PidFile $Name
    return $true
}

# Reads the per-user configuration through the application's own loader, so
# the launcher and the GUI can never disagree about paths.
function Get-AppConfig {
    if (-not (Test-Path $VenvPython)) { return $null }
    $script = Join-Path $PSScriptRoot "config_dump.py"
    $json = & $VenvPython $script 2>$null
    if ($LASTEXITCODE -ne 0 -or -not $json) { return $null }
    try {
        return $json | ConvertFrom-Json
    } catch {
        return $null
    }
}

function Get-LoopbackHost([string]$Url) {
    try {
        $uri = [System.Uri]$Url
        $hostName = $uri.Host
        if ($hostName -eq "localhost") { return "127.0.0.1" }
        return $hostName
    } catch {
        return "127.0.0.1"
    }
}

function Get-PortFromUrl([string]$Url, [int]$Default) {
    try {
        $uri = [System.Uri]$Url
        if ($uri.Port -gt 0) { return $uri.Port }
    } catch { }
    return $Default
}

function Find-Ollama {
    # A runtime imported from the offline bundle lives inside the project, so a
    # demo laptop needs no installation and no administrator rights.
    if (Test-Path $BundledOllamaExe) { return $BundledOllamaExe }

    $command = Get-Command ollama -ErrorAction SilentlyContinue
    if ($command -and $command.Source) { return $command.Source }
    $candidates = @(
        (Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama.exe"),
        (Join-Path $env:ProgramFiles "Ollama\ollama.exe")
    )
    foreach ($candidate in $candidates) {
        if (Test-Path $candidate) { return $candidate }
    }
    return $null
}

function Test-BundledRuntime([string]$ExePath) {
    # The bundled runtime belongs to this project, so stopping it cannot break
    # another application the way stopping a system-wide Ollama could.
    if (-not $ExePath) { return $false }
    $root = (Join-Path $ToolsDir "ollama").TrimEnd("\") + "\"
    return $ExePath.StartsWith($root, [System.StringComparison]::OrdinalIgnoreCase)
}

function Set-OllamaBind([string]$HostUrl) {
    # ollama serve only listens where OLLAMA_HOST says; without it a runtime
    # started here would ignore a custom address from Settings.
    $bindHost = Get-LoopbackHost $HostUrl
    $port = Get-PortFromUrl $HostUrl 11434
    $env:OLLAMA_HOST = "${bindHost}:$port"
}

function Show-Tail([string]$Path, [int]$Lines = 15) {
    if (Test-Path $Path) {
        Write-Host "Last $Lines lines of $Path :" -ForegroundColor Yellow
        Get-Content -Path $Path -Tail $Lines -ErrorAction SilentlyContinue | ForEach-Object {
            Write-Host "  $_"
        }
    }
}

function Get-FreeSpaceGB([string]$Path) {
    # Walk up to the nearest existing folder so a data folder that has not been
    # created yet still reports the free space of the drive it will live on.
    $probe = $Path
    while ($probe -and -not (Test-Path -LiteralPath $probe)) {
        $probe = Split-Path -LiteralPath $probe -Parent
    }
    if (-not $probe) { return $null }
    try {
        $root = [System.IO.Path]::GetPathRoot($probe)
        if (-not $root) { return $null }
        $drive = New-Object System.IO.DriveInfo($root)
        return [math]::Round($drive.AvailableFreeSpace / 1GB, 1)
    } catch {
        return $null
    }
}

function Test-PortListening([int]$Port) {
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $connect = $client.ConnectAsync("127.0.0.1", $Port)
        return ($connect.Wait(300) -and $client.Connected)
    } catch {
        return $false
    } finally {
        $client.Dispose()
    }
}

function Test-PythonEnvironment {
    # A present .venv is not enough: an interrupted install leaves the folder
    # behind with the core packages missing, which used to fail much later.
    if (-not (Test-Path $VenvPython)) { return $false }
    & $VenvPython -c "import PySide6, fastapi, pytsk3" 2>$null
    return $LASTEXITCODE -eq 0
}

function Get-BundleInfo {
    # Everything a machine without internet needs, in one object, so setup and
    # the doctor can tell the user exactly what is missing before it tries.
    $wheels = @(Get-ChildItem -Path $PackagesDir -Filter "*.whl" -ErrorAction SilentlyContinue)
    $wheelBytes = 0
    if ($wheels.Count -gt 0) {
        $wheelSum = ($wheels | Measure-Object -Property Length -Sum).Sum
        if ($wheelSum) { $wheelBytes = $wheelSum }
    }
    $models = Join-Path $ProjectDir "models\ollama"
    $modelBytes = 0
    if (Test-Path $models) {
        $sum = (Get-ChildItem -Path $models -Recurse -File -ErrorAction SilentlyContinue |
            Measure-Object -Property Length -Sum).Sum
        if ($sum) { $modelBytes = $sum }
    }
    $manifestWheels = -1
    $manifestWheelBytes = 0
    $manifestModelGB = 0
    $manifestPath = Join-Path $PackagesDir "offline-manifest.json"
    if (Test-Path $manifestPath) {
        try {
            $manifest = Get-Content -Path $manifestPath -Raw | ConvertFrom-Json
            if ($null -ne $manifest.wheels) { $manifestWheels = [int]$manifest.wheels }
            if ($null -ne $manifest.wheel_bytes) { $manifestWheelBytes = [long]$manifest.wheel_bytes }
            if ($null -ne $manifest.model_bytes) {
                $manifestModelGB = [math]::Round($manifest.model_bytes / 1GB, 2)
            }
        } catch { }
    }
    [pscustomobject]@{
        Manifest       = Test-Path $manifestPath
        ManifestWheels = $manifestWheels
        ManifestWheelBytes = $manifestWheelBytes
        ManifestModelGB = $manifestModelGB
        Wheels         = $wheels.Count
        WheelBytes     = $wheelBytes
        WheelGB        = [math]::Round($wheelBytes / 1GB, 2)
        Qdrant         = Test-Path (Join-Path $PackagesDir "qdrant-x86_64-pc-windows-msvc.zip")
        Ollama         = Test-Path (Join-Path $PackagesDir "ollama-windows-cpu.zip")
        Python         = @(Get-ChildItem -Path $PackagesDir -Filter "python-3.12*-amd64.exe" -ErrorAction SilentlyContinue).Count -gt 0
        Models         = Test-Path (Join-Path $models "manifests")
        ModelGB        = [math]::Round($modelBytes / 1GB, 2)
    }
}
