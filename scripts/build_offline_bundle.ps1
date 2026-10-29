param(
    [switch]$SkipWheels,
    [switch]$SkipTools,
    [switch]$SkipModels
)

# Builds the self-contained bundle used to install IDFA on an offline machine.
#
#   packages\   wheels for requirements.txt, the Qdrant archive, the Python
#               installer and a portable Ollama runtime
#   models\     the weights for the chat and embedding models
#
# Run this from a connected Windows machine with a working .venv and Ollama.
# It never deletes anything the user already has; existing files are reused.

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "_common.ps1")

$QdrantVersion = "1.20.0"
$QdrantUrl = "https://github.com/qdrant/qdrant/releases/download/v$QdrantVersion/qdrant-x86_64-pc-windows-msvc.zip"
$PythonVersion = "3.12.10"
$PythonUrl = "https://www.python.org/ftp/python/$PythonVersion/python-$PythonVersion-amd64.exe"
$ModelsDir = Join-Path $ProjectDir "models\ollama"

function New-OllamaRuntimeBundle {
    # The official installer is 1.6 GB, almost all of it CUDA and ROCm runtimes.
    # A demo laptop needs none of that, so the bundle carries the program and
    # its CPU libraries only: about 65 MB, unpacked next to the project.
    $ollamaExe = Find-Ollama
    if (-not $ollamaExe) { return $false }

    $root = Split-Path $ollamaExe -Parent
    $libSource = Join-Path $root "lib\ollama"
    if (-not (Test-Path $libSource)) { return $false }

    $staging = Join-Path $env:TEMP "idfa_ollama_stage"
    if (Test-Path $staging) { Remove-Item $staging -Recurse -Force }
    New-Item -ItemType Directory -Path (Join-Path $staging "lib\ollama") -Force | Out-Null

    Copy-Item -Path $ollamaExe -Destination $staging -Force
    Get-ChildItem -Path $libSource -File | ForEach-Object {
        Copy-Item -Path $_.FullName -Destination (Join-Path $staging "lib\ollama") -Force
    }

    $zip = Join-Path $PackagesDir "ollama-windows-cpu.zip"
    if (Test-Path $zip) { Remove-Item $zip -Force }
    Compress-Archive -Path (Join-Path $staging "*") -DestinationPath $zip -CompressionLevel Optimal
    Remove-Item $staging -Recurse -Force
    return $true
}

function Get-ModelSource {
    if ($env:OLLAMA_MODELS -and (Test-Path $env:OLLAMA_MODELS)) {
        return $env:OLLAMA_MODELS
    }
    $default = Join-Path $env:USERPROFILE ".ollama\models"
    if (Test-Path $default) { return $default }
    return $null
}

function Copy-ModelManifest([string]$Root, [string]$RelativePath, [string]$DigestFolder) {
    $source = Join-Path $Root $RelativePath
    if (-not (Test-Path $source)) { return @() }

    $destination = Join-Path $ModelsDir $RelativePath
    New-Item -ItemType Directory -Path (Split-Path $destination -Parent) -Force | Out-Null
    Copy-Item -Path $source -Destination $destination -Force

    $manifest = Get-Content -Path $source -Raw | ConvertFrom-Json
    $digests = @($manifest.config.digest) + @($manifest.layers | ForEach-Object { $_.digest })
    return @($digests | Where-Object { $_ })
}

function Copy-Model([string]$Model) {
    $parts = $Model.Split(":")
    $name = $parts[0]
    $tag = "latest"
    if ($parts.Count -gt 1 -and $parts[1]) { $tag = $parts[1] }

    $source = Get-ModelSource
    if (-not $source) {
        Write-Warn "No Ollama model store found; skipping $Model"
        return $false
    }

    $digests = @()
    $digests += Copy-ModelManifest $source "manifests\registry.ollama.ai\library\$name\$tag" "blobs"
    $digests += Copy-ModelManifest $source "manifests-v2\ollama.com\library\$name\$tag" "blobs"
    if ($digests.Count -eq 0) {
        Write-Warn "$Model is not in the local Ollama store (looked in $source)"
        return $false
    }

    $blobDir = Join-Path $ModelsDir "blobs"
    New-Item -ItemType Directory -Path $blobDir -Force | Out-Null
    $copied = 0
    foreach ($digest in ($digests | Select-Object -Unique)) {
        $fileName = $digest.Replace(":", "-")
        $sourceBlob = Join-Path $source (Join-Path "blobs" $fileName)
        $targetBlob = Join-Path $blobDir $fileName
        if (Test-Path $targetBlob) { continue }
        if (-not (Test-Path $sourceBlob)) {
            Write-Warn "Blob $digest for $Model is missing from the store"
            continue
        }
        Copy-Item -Path $sourceBlob -Destination $targetBlob -Force
        $copied++
    }
    Write-Ok "$Model bundled ($copied new blobs)"
    return $true
}

Write-Host "============================================================" -ForegroundColor Green
Write-Host " IDFA - building the offline bundle" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green

New-Item -ItemType Directory -Path $PackagesDir -Force | Out-Null

if (-not $SkipWheels) {
    Write-Step "Python wheels"
    if (-not (Test-Path $VenvPython)) {
        throw "No .venv found. Run SETUP_IDFA.bat first."
    }
    & $VenvPython -m pip download -r (Join-Path $ProjectDir "requirements.txt") `
        -d $PackagesDir --only-binary=:all: `
        --platform win_amd64 --python-version 3.12 --implementation cp --abi cp312
    if ($LASTEXITCODE -ne 0) {
        throw "Could not download every wheel. Check the pip output above."
    }
    Write-Ok "Wheels downloaded to $PackagesDir"
}

if (-not $SkipTools) {
    Write-Step "Qdrant"
    $qdrantArchive = Join-Path $PackagesDir "qdrant-x86_64-pc-windows-msvc.zip"
    if ((Test-Path $qdrantArchive) -and ((Get-Item $qdrantArchive).Length -gt 5MB)) {
        Write-Ok "Qdrant archive already bundled"
    } else {
        if (-not (Get-RemoteFile $QdrantUrl $qdrantArchive)) { throw "Could not download Qdrant from $QdrantUrl" }
        Write-Ok "Qdrant $QdrantVersion downloaded"
    }

    Write-Step "Ollama runtime"
    $ollamaRuntime = Join-Path $PackagesDir "ollama-windows-cpu.zip"
    if ((Test-Path $ollamaRuntime) -and ((Get-Item $ollamaRuntime).Length -gt 5MB)) {
        Write-Ok "Ollama CPU runtime already bundled"
    } elseif (New-OllamaRuntimeBundle) {
        $size = [math]::Round((Get-Item $ollamaRuntime).Length/1MB, 1)
        Write-Ok "Ollama CPU runtime bundled ($size MB)"
    } else {
        Write-Warn "No Ollama installation found, so the bundle has no runtime."
        Write-Host "  Install Ollama once from https://ollama.com/download/windows and re-run this script." -ForegroundColor Gray
    }

    Write-Step "Python installer"
    $pythonInstaller = Get-ChildItem -Path $PackagesDir -Filter "python-3.12*-amd64.exe" -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($pythonInstaller) {
        Write-Ok "Python installer already bundled ($($pythonInstaller.Name))"
    } else {
        $pythonTarget = Join-Path $PackagesDir "python-$PythonVersion-amd64.exe"`
        if (-not (Get-RemoteFile $PythonUrl $pythonTarget)) { throw "Could not download Python from $PythonUrl" }
        Write-Ok "Python $PythonVersion installer downloaded"
    }
}

if (-not $SkipModels) {
    Write-Step "AI models"
    $config = Get-AppConfig
    $chatModel = "phi3:mini"
    $embeddingModel = "all-minilm"
    if ($null -ne $config) {
        if ($config.ollama_model) { $chatModel = $config.ollama_model }
        if ($config.embedding_model) { $embeddingModel = $config.embedding_model }
    }
    Copy-Model $chatModel | Out-Null
    Copy-Model $embeddingModel | Out-Null
}

function Split-LargeModelBlobs {
    # GitHub LFS Free/Pro rejects individual objects above 2 GB. Ollama's
    # phi3:mini layer is larger, so retain its bytes as 1 GB chunks in the
    # distributable. setup.ps1 reassembles them in the Ollama model store.
    $blobDir = Join-Path $ModelsDir "blobs"
    if (-not (Test-Path -LiteralPath $blobDir)) { return }
    $chunkBytes = 1GB
    $buffer = New-Object byte[] (1MB)
    Get-ChildItem -LiteralPath $blobDir -File | Where-Object {
        $_.Length -gt 1800000000 -and $_.Name -notmatch '\.part\d{4}$'
    } | ForEach-Object {
        $blob = $_
        $blobStream = [System.IO.File]::OpenRead($blob.FullName)
        $index = 1
        $written = 0L
        try {
            while ($blobStream.Position -lt $blobStream.Length) {
                $partPath = "{0}.part{1:D4}" -f $blob.FullName, $index
                $partStream = [System.IO.File]::Open($partPath, [System.IO.FileMode]::Create,
                    [System.IO.FileAccess]::Write, [System.IO.FileShare]::None)
                $remainingBlob = $blobStream.Length - $blobStream.Position
                [long]$partLength = if ($remainingBlob -gt $chunkBytes) { $chunkBytes } else { $remainingBlob }
                try {
                    $remaining = $partLength
                    while ($remaining -gt 0) {
                        $read = $blobStream.Read($buffer, 0, [int][math]::Min($buffer.Length, [double]$remaining))
                        if ($read -le 0) { throw "Unexpected end of model blob $($blob.Name)" }
                        $partStream.Write($buffer, 0, $read)
                        $remaining -= $read
                        $written += $read
                    }
                } finally { $partStream.Dispose() }
                $index++
            }
        } finally { $blobStream.Dispose() }
        if ($written -ne $blob.Length) { throw "Split model blob size mismatch: $($blob.Name)" }
        Remove-Item -LiteralPath $blob.FullName -Force
        Write-Ok "Split large model layer into $($index - 1) Git LFS-sized parts"
    }
}

Split-LargeModelBlobs

Write-Step "Manifest"
$wheels = @(Get-ChildItem $PackagesDir -Filter "*.whl")
if ($wheels.Count -eq 0) {
    Write-Warn "No wheels in $PackagesDir, so the offline marker was not written."
    Write-Host "  setup.ps1 would treat the cache as complete. Re-run without -SkipWheels." -ForegroundColor Gray
    exit 1
}
$weightBytes = 0
if (Test-Path $ModelsDir) {
    $weightBytes = (Get-ChildItem $ModelsDir -Recurse -File | Measure-Object -Property Length -Sum).Sum
}
$toolBytes = 0
foreach ($name in @("qdrant-x86_64-pc-windows-msvc.zip", "ollama-windows-cpu.zip")) {
    $path = Join-Path $PackagesDir $name
    if (Test-Path $path) { $toolBytes += (Get-Item $path).Length }
}
$pythonInstallerBytes = 0
$pythonInstaller = Get-ChildItem -Path $PackagesDir -Filter "python-3.12*-amd64.exe" -ErrorAction SilentlyContinue |
    Select-Object -First 1
if ($pythonInstaller) { $pythonInstallerBytes = $pythonInstaller.Length }

$manifest = [ordered]@{
    created = (Get-Date).ToString("yyyy-MM-dd")
    python = "3.12"
    platform = "win_amd64"
    wheels = $wheels.Count
    wheel_bytes = ($wheels | Measure-Object -Property Length -Sum).Sum
    tool_bytes = $toolBytes
    python_installer_bytes = $pythonInstallerBytes
    model_bytes = $weightBytes
}
$manifest | ConvertTo-Json | Set-Content -Path (Join-Path $PackagesDir "offline-manifest.json") -Encoding UTF8

$totalMb = [math]::Round((($manifest.wheel_bytes + $manifest.tool_bytes + $manifest.python_installer_bytes + $manifest.model_bytes) / 1MB), 1)
Write-Ok "Bundle manifest written ($($wheels.Count) wheels, ~$totalMb MB in total)"

Write-Host ""
Write-Host "Copy the project folder, packages\ and models\ to the offline machine," -ForegroundColor Cyan
Write-Host "then run SETUP_IDFA.bat -Offline there." -ForegroundColor Cyan

