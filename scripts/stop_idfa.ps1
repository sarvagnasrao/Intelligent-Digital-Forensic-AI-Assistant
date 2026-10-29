param(
    [switch]$IncludeOllama
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "_common.ps1")

function Stop-PortOwner([int]$Port, [string]$Name, [string]$ExpectedName, [string]$PathPart, [string]$CommandPattern) {
    $owner = Get-PortOwner $Port
    if (-not $owner) { return $false }

    $owned = Get-OwnedProcess $owner.Id $ExpectedName $PathPart $CommandPattern
    if (-not $owned) {
        Write-Warn "Port $Port is held by $(Format-Process $owner); leaving it alone."
        return $false
    }

    Write-Host "Stopping $Name on port $Port ($(Format-Process $owner))..."
    try {
        Stop-Process -Id $owner.Id -Force -ErrorAction Stop
    } catch {
        Write-Warn "Could not stop $Name (pid $($owner.Id)): $($_.Exception.Message)"
        return $false
    }
    return $true
}

Write-Host "Stopping IDFA services..." -ForegroundColor Yellow

$config = Get-AppConfig
$workerPort = 8000
$qdrantPort = 6333
if ($null -ne $config) {
    $workerPort = Get-PortFromUrl $config.worker_url 8000
    $qdrantPort = Get-PortFromUrl $config.qdrant_url 6333
}

$stoppedWorker = Stop-ManagedProcess "worker" "python" ".venv" "worker\main.py"
if (-not $stoppedWorker) {
    Stop-PortOwner $workerPort "forensic worker" "python" ".venv" "worker\main.py" | Out-Null
}

$stoppedQdrant = Stop-ManagedProcess "qdrant" "qdrant" "qdrant" ""
if (-not $stoppedQdrant) {
    Stop-PortOwner $qdrantPort "Qdrant" "qdrant" "qdrant" "" | Out-Null
}

# Only an Ollama process this installation started is stopped: the launcher
# records it in a PID file. A system-wide server owned by another application
# is left alone unless -IncludeOllama is given.
$ollamaPort = 11434
if ($null -ne $config) {
    $ollamaPort = Get-PortFromUrl $config.ollama_host 11434
}
$stoppedOllama = Stop-ManagedProcess "ollama-idfa" "ollama" "" ""
if (-not $stoppedOllama) {
    $stoppedOllama = Stop-ManagedProcess "ollama-bundled" "ollama" "tools\ollama" ""
}
if (-not $stoppedOllama) {
    $stoppedOllama = Stop-PortOwner $ollamaPort "bundled Ollama" "ollama" "tools\ollama" ""
}

if ($IncludeOllama) {
    $ollama = Get-Process -Name "ollama" -ErrorAction SilentlyContinue
    if ($ollama) {
        Write-Host "Stopping Ollama..."
        $ollama | Stop-Process -Force -ErrorAction SilentlyContinue
    }
}

Write-Host ""
Write-Host "IDFA services stopped." -ForegroundColor Green
Write-Host "Close the GUI window separately if it is still open." -ForegroundColor Gray
if (-not $IncludeOllama) {
    if ($stoppedOllama) {
        Write-Host "The Ollama instance started by IDFA was stopped." -ForegroundColor Gray
    } else {
        Write-Host "Ollama was left running because other applications may use it (use -IncludeOllama to stop it)." -ForegroundColor Gray
    }
}
