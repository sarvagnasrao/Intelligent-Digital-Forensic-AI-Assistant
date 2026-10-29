param(
    [switch]$NoGui,
    [switch]$Status,
    [switch]$Yes,
    [switch]$NoSetup
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "_common.ps1")

function Initialize-Environment {
    # A clone of the repository has no .venv, and an interrupted setup leaves a
    # half-installed one. Both used to fail with "Run SETUP_IDFA.bat first" and
    # no way forward, so the launcher now offers to do it itself.
    if (Test-PythonEnvironment) { return $true }

    if ($NoSetup) {
        Write-Fail "IDFA is not prepared on this computer yet (missing or incomplete .venv)."
        Write-Host "Run SETUP_IDFA.bat, then try again." -ForegroundColor Yellow
        return $false
    }

    Write-Host ""
    Write-Warn "IDFA is not prepared on this computer yet (missing or incomplete .venv)."
    Write-Host "  Setup creates the environment. When packages\ and models\ are present," -ForegroundColor Gray
    Write-Host "  everything is installed from them without downloading anything." -ForegroundColor Gray
    $answer = "y"
    if (-not $Yes) {
        $answer = Read-Host "Run SETUP_IDFA.bat now? [Y/n]"
    }
    if ($answer -and $answer.Trim() -match "^(?i)n") {
        Write-Host "Run SETUP_IDFA.bat when you are ready." -ForegroundColor Yellow
        return $false
    }

    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "setup.ps1")
    if ($LASTEXITCODE -ne 0 -or -not (Test-PythonEnvironment)) {
        Write-Fail "Setup did not finish. Fix the messages above, then run SETUP_IDFA.bat."
        return $false
    }
    Write-Ok "Environment ready"
    return $true
}

if (-not (Initialize-Environment)) { exit 1 }

function Wait-ForHttp([string]$Url, [int]$Attempts = 60, [int]$DelayMs = 500) {
    for ($attempt = 0; $attempt -lt $Attempts; $attempt++) {
        if (Test-HttpOk $Url 3) { return $true }
        Start-Sleep -Milliseconds $DelayMs
    }
    return $false
}

function Start-Ollama([string]$HostUrl) {
    if (Test-HttpOk "$HostUrl/api/tags" 3) {
        Write-Ok "Ollama already running at $HostUrl"
        return $true
    }
    $exe = Find-Ollama
    if (-not $exe) {
        Write-Warn "Ollama is not installed. AI replies and semantic search stay unavailable."
        return $false
    }
    Write-Host "Starting Ollama..."
    Set-OllamaBind $HostUrl
    $process = Start-Process -FilePath $exe -ArgumentList "serve" -WindowStyle Hidden -PassThru
    Save-PidFile "ollama-idfa" $process.Id
    if (Wait-ForHttp "$HostUrl/api/tags" 40) {
        Write-Ok "Ollama running at $HostUrl"
        return $true
    }
    Write-Warn "Ollama did not answer at $HostUrl"
    return $false
}

function Start-Qdrant($Config) {
    $url = $Config.qdrant_url
    if (Test-HttpOk "$url/healthz" 3) {
        Write-Ok "Qdrant already running at $url"
        return $true
    }

    $port = Get-PortFromUrl $url 6333
    $owner = Get-PortOwner $port
    if ($owner) {
        Write-Warn "Port $port is held by $(Format-Process $owner), but it is not answering like Qdrant."
        return $false
    }

    if (-not (Test-Path $QdrantExe)) {
        Write-Warn "Qdrant is not installed at $QdrantExe. Run SETUP_IDFA.bat."
        return $false
    }

    $storage = $Config.qdrant_storage
    if (-not $storage) { $storage = Join-Path $Config.data_dir "qdrant" }
    if (-not (Test-Path $storage)) {
        New-Item -ItemType Directory -Path $storage -Force | Out-Null
    }

    Write-Host "Starting Qdrant (storage: $storage)..."
    $env:QDRANT__STORAGE__STORAGE_PATH = $storage
    $env:QDRANT__TELEMETRY_DISABLED = "true"
    $log = Join-Path $Config.logs_dir "qdrant.log"
    $errorLog = Join-Path $Config.logs_dir "qdrant.err.log"
    $process = Start-Process -FilePath $QdrantExe `
        -WorkingDirectory (Split-Path $QdrantExe -Parent) `
        -RedirectStandardOutput $log `
        -RedirectStandardError $errorLog `
        -WindowStyle Hidden -PassThru
    Save-PidFile "qdrant" $process.Id

    if (Wait-ForHttp "$url/healthz" 40) {
        Write-Ok "Qdrant running at $url"
        return $true
    }
    Write-Warn "Qdrant did not become healthy. See $errorLog"
    Show-Tail $errorLog 10
    return $false
}

function Start-Worker($Config) {
    $url = $Config.worker_url
    if (Test-HttpOk "$url/health" 4) {
        Write-Ok "Forensic worker already running at $url"
        return $true
    }

    $port = Get-PortFromUrl $url 8000
    $owner = Get-PortOwner $port
    if ($owner) {
        throw "Port $port is already used by $(Format-Process $owner). Stop that process or change the worker URL in Settings."
    }

    $bindHost = Get-LoopbackHost $url
    Write-Host "Starting forensic worker on ${bindHost}:$port..."
    $env:IDFA_WORKER_HOST = $bindHost
    $env:IDFA_WORKER_PORT = "$port"
    $env:IDFA_OLLAMA_HOST = $Config.ollama_host
    $env:IDFA_OLLAMA_MODEL = $Config.ollama_model
    $env:IDFA_EMBEDDING_MODEL = $Config.embedding_model
    $env:IDFA_QDRANT_URL = $Config.qdrant_url

    $log = Join-Path $Config.logs_dir "worker.log"
    $errorLog = Join-Path $Config.logs_dir "worker.err.log"
    $process = Start-Process -FilePath $VenvPython `
        -ArgumentList @("worker\main.py") `
        -WorkingDirectory $ProjectDir `
        -RedirectStandardOutput $log `
        -RedirectStandardError $errorLog `
        -WindowStyle Hidden -PassThru
    Save-PidFile "worker" $process.Id

    if (Wait-ForHttp "$url/health" 120) {
        Write-Ok "Forensic worker running at $url"
        return $true
    }
    Write-Fail "The forensic worker did not become healthy."
    Show-Tail $errorLog 20
    Show-Tail $log 10
    return $false
}

function Show-Status($Config) {
    $health = Get-Json "$($Config.worker_url)/health"
    $ollamaNeeded = ($Config.chat_provider -ne "openai" -or $Config.embedding_provider -ne "openai")
    $ollamaOk = if ($ollamaNeeded) { Test-HttpOk "$($Config.ollama_host)/api/tags" 3 } else { $true }
    $qdrantOk = Test-HttpOk "$($Config.qdrant_url)/healthz" 3

    $workerState = if ($health) { "RUNNING" } else { "DOWN" }
    $workerColor = if ($health) { "Green" } else { "Red" }
    Write-Host ("{0,-12} {1,-8} {2}" -f "Worker", $workerState, $Config.worker_url) -ForegroundColor $workerColor
    if ($health) {
        $tsk = if ($health.pytsk3) { "pytsk3 ok" } else { "pytsk3 MISSING" }
        $ewf = if ($health.pyewf) { "pyewf ok" } else { "pyewf missing" }
        Write-Host ("{0,-12} {1,-8} {2}" -f "", "", "$tsk, $ewf") -ForegroundColor Gray
    }

    $ollamaColor = if ($ollamaOk) { "Green" } else { "Yellow" }
    $ollamaState = if (-not $ollamaNeeded) { "NOT NEEDED" } elseif ($ollamaOk) { "RUNNING" } else { "DOWN" }
    Write-Host ("{0,-12} {1,-8} {2}" -f "Ollama", $ollamaState, $Config.ollama_host) -ForegroundColor $ollamaColor

    if ($health) {
        $cloudEmbeddings = ($Config.embedding_provider -eq "openai")
        $embState = if ($cloudEmbeddings) { "CLOUD" } elseif ($health.embeddings) { "READY" } else { "MISSING" }
        $embColor = if ($cloudEmbeddings -or $health.embeddings) { "Green" } else { "Yellow" }
        Write-Host ("{0,-12} {1,-8} {2}" -f "Embedding", $embState, $Config.embedding_model) -ForegroundColor $embColor
    }

    $qdrantColor = if ($qdrantOk) { "Green" } else { "Yellow" }
    $qdrantState = if ($qdrantOk) { "RUNNING" } else { "DOWN" }
    Write-Host ("{0,-12} {1,-8} {2}" -f "Qdrant", $qdrantState, $Config.qdrant_url) -ForegroundColor $qdrantColor

    Write-Host ("{0,-12} {1}" -f "Data", $Config.data_dir) -ForegroundColor Gray
    Write-Host ("{0,-12} {1}" -f "Logs", $Config.logs_dir) -ForegroundColor Gray

    if ($ollamaNeeded -and -not $ollamaOk) {
        Write-Warn "AI replies need Ollama. Search and examination still work."
    }
    if (-not $qdrantOk) {
        Write-Warn "Semantic search needs Qdrant. Keyword search still works."
    }
}

$config = Get-AppConfig
if ($null -eq $config) {
    Write-Fail "Could not read the IDFA configuration. Run SETUP_IDFA.bat first."
    exit 1
}

if (-not (Test-Path $config.logs_dir)) {
    New-Item -ItemType Directory -Path $config.logs_dir -Force | Out-Null
}

if ($Status) {
    Show-Status $config
    exit 0
}

Write-Host "============================================================" -ForegroundColor Green
Write-Host " IDFA - starting local services" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
Write-Host "Project: $ProjectDir"
Write-Host "Data:    $($config.data_dir)"

$ollamaNeeded = ($config.chat_provider -ne "openai" -or $config.embedding_provider -ne "openai")
if ($ollamaNeeded) {
    Start-Ollama $config.ollama_host | Out-Null
} else {
    Stop-ManagedProcess "ollama-idfa" "ollama" "" "" | Out-Null
    Stop-ManagedProcess "ollama-bundled" "ollama" "tools\ollama" "" | Out-Null
    Write-Ok "Ollama not needed for cloud chat and cloud embeddings; IDFA-managed instance stopped"
}
Start-Qdrant $config | Out-Null
$workerOk = Start-Worker $config

Write-Host ""
Show-Status $config
Write-Host ""

if (-not $workerOk) {
    Write-Fail "Examination and AI endpoints are unavailable because the worker is down."
    exit 1
}

if ($NoGui) {
    Write-Host "Services are running in the background. Stop them with STOP_IDFA.bat." -ForegroundColor Cyan
    exit 0
}

Write-Host "Launching the IDFA GUI. Services keep running after the GUI closes." -ForegroundColor Cyan
Push-Location $ProjectDir
try {
    & $VenvPython -m app
    $guiExit = $LASTEXITCODE
} finally {
    Pop-Location
}

if ($guiExit -ne 0) {
    Write-Warn "The GUI exited with code $guiExit. See the logs in $($config.logs_dir)."
}
Write-Host "Services are still running. Stop them with STOP_IDFA.bat." -ForegroundColor Gray
exit 0
