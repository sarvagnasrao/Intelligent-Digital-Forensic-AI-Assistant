# Removes everything SETUP_IDFA.bat (and START_IDFA.bat) created on this
# computer: the Python environment, the Qdrant/Ollama runtimes in tools\,
# generated caches, the shortcuts and the PID files. Case data, the source
# code, the offline bundle and the configuration are kept unless you ask for
# them with -PurgeData / -RemoveBundle.
#
#   UNINSTALL_IDFA.bat              interactive, keeps cases
#   UNINSTALL_IDFA.bat -DryRun      show what would be removed
#   UNINSTALL_IDFA.bat -Yes         no questions (still keeps data)
#   UNINSTALL_IDFA.bat -PurgeData   also delete the case database and evidence
#   UNINSTALL_IDFA.bat -RemoveModels  also delete phi3:mini/all-minilm from Ollama
#   UNINSTALL_IDFA.bat -RemoveBundle  also delete packages\ and models\
#
param(
    [switch]$Yes,
    [switch]$DryRun,
    [switch]$PurgeData,
    [switch]$RemoveModels,
    [switch]$RemoveBundle
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "_common.ps1")

$script:Failures = 0
$script:Removed = 0

function Get-PathSizeMB([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) { return 0 }
    try {
        $sum = (Get-ChildItem -LiteralPath $Path -Recurse -File -Force -ErrorAction SilentlyContinue |
            Measure-Object -Property Length -Sum).Sum
        if ($sum) { return [math]::Round($sum / 1MB, 1) }
    } catch { }
    return 0
}

function Remove-Target([string]$Path, [string]$Label) {
    if (-not (Test-Path -LiteralPath $Path)) { return }
    $size = Get-PathSizeMB $Path
    if ($DryRun) {
        Write-Info "would remove $Label ($size MB): $Path"
        return
    }
    try {
        Remove-Item -LiteralPath $Path -Recurse -Force -ErrorAction Stop
        Write-Ok "Removed $Label ($size MB)"
        $script:Removed++
    } catch {
        Write-Fail "Could not remove $Label at $Path : $($_.Exception.Message)"
        $script:Failures++
    }
}

function Find-CacheDirs {
    # Generated caches only. .venv, tools, packages and models are removed as a
    # whole, so walking into them would list thousands of package caches.
    $results = @()
    $skip = @(".venv", "tools", "packages", "models", ".git", "node_modules", "dist")
    $queue = New-Object System.Collections.Queue
    $queue.Enqueue($ProjectDir)
    while ($queue.Count -gt 0) {
        $dir = $queue.Dequeue()
        foreach ($child in (Get-ChildItem -LiteralPath $dir -Directory -Force -ErrorAction SilentlyContinue)) {
            if ($skip -contains $child.Name) { continue }
            if ($child.Name -eq "__pycache__" -or $child.Name -like ".*_cache") {
                $results += $child.FullName
                continue
            }
            $queue.Enqueue($child.FullName)
        }
    }
    return $results
}

function Remove-EmptyDir([string]$Path) {
    if ($DryRun -or -not (Test-Path -LiteralPath $Path)) { return }
    if (-not (Get-ChildItem -LiteralPath $Path -Force -ErrorAction SilentlyContinue)) {
        Remove-Item -LiteralPath $Path -Force -ErrorAction SilentlyContinue
    }
}

function Get-RunningGui {
    # The window is not a service, so it has no PID file. Match the interpreter
    # inside .venv running `-m app`.
    try {
        Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" -ErrorAction Stop |
            Where-Object {
                $_.ExecutablePath -and ($_.ExecutablePath -like "$VenvDir*") -and
                $_.CommandLine -and ($_.CommandLine -like "*-m app*")
            }
    } catch {
        @()
    }
}

function Test-SafeDataPath([string]$Path) {
    # -PurgeData deletes evidence, so refuse anything that is not a dedicated
    # folder: a drive root, the project, the home/profile/Documents folder or one
    # of their parents.
    if (-not $Path) { return $false }
    try {
        $full = [System.IO.Path]::GetFullPath($Path).TrimEnd('\')
    } catch {
        return $false
    }
    if (-not $full) { return $false }
    $root = [System.IO.Path]::GetPathRoot($full)
    if ($full -eq $root.TrimEnd('\')) { return $false }
    $forbidden = @(
        $ProjectDir,
        $env:USERPROFILE,
        ([Environment]::GetFolderPath("UserProfile")),
        ([Environment]::GetFolderPath("MyDocuments")),
        ([Environment]::GetFolderPath("Desktop"))
    )
    $projectFull = [System.IO.Path]::GetFullPath($ProjectDir).TrimEnd('\')
    if ($full -eq $projectFull) { return $false }
    if ($projectFull.StartsWith($full + "\", [System.StringComparison]::OrdinalIgnoreCase)) { return $false }
    foreach ($entry in $forbidden) {
        if (-not $entry) { continue }
        $candidate = [System.IO.Path]::GetFullPath($entry).TrimEnd('\')
        if ($full -eq $candidate) { return $false }
    }
    return $true
}

function Get-ManifestDigests([string]$Content) {
    $matches = [regex]::Matches($Content, "sha256:[a-f0-9]{64}")
    return @($matches | ForEach-Object { $_.Value } | Sort-Object -Unique)
}

function Get-OllamaStore {
    $store = $env:OLLAMA_MODELS
    if (-not $store) { $store = Join-Path $env:USERPROFILE ".ollama\models" }
    return $store
}

function Remove-ImportedModels {
    # setup.ps1 copies the bundle's phi3:mini and all-minilm manifests and blobs
    # into the user's Ollama store. Delete only those entries, and only blobs no
    # remaining manifest references, so another model keeps working.
    $store = Get-OllamaStore
    if (-not (Test-Path -LiteralPath $store)) {
        Write-Info "No Ollama model store at $store; nothing to remove"
        return
    }
    $roots = @(
        (Join-Path $store "manifests"),
        (Join-Path $store "manifests-v2")
    ) | Where-Object { Test-Path -LiteralPath $_ }
    if (-not $roots) {
        Write-Info "No Ollama manifests at $store; nothing to remove"
        return
    }

    $wanted = @(
        @{ Name = "phi3"; Tag = "mini" },
        @{ Name = "all-minilm"; Tag = "latest" }
    )
    $targets = @()
    foreach ($root in $roots) {
        Get-ChildItem -LiteralPath $root -Recurse -File -ErrorAction SilentlyContinue | ForEach-Object {
            $relative = $_.FullName.Substring($root.Length).TrimStart('\')
            $parts = $relative -split "\\"
            if ($parts.Count -lt 2) { return }
            $tag = $parts[$parts.Count - 1]
            $name = $parts[$parts.Count - 2]
            foreach ($entry in $wanted) {
                if ($name -eq $entry.Name -and $tag -eq $entry.Tag) {
                    $targets += $_
                }
            }
        }
    }
    $targets = @($targets | Sort-Object FullName -Unique)

    if (-not $targets) {
        Write-Info "phi3:mini and all-minilm are not in the Ollama store"
        return
    }

    $removedDigests = @{}
    foreach ($manifest in $targets) {
        $content = Get-Content -LiteralPath $manifest.FullName -Raw -ErrorAction SilentlyContinue
        foreach ($digest in (Get-ManifestDigests $content)) { $removedDigests[$digest] = $true }
        if ($DryRun) {
            Write-Info "would remove Ollama manifest $($manifest.FullName)"
        } else {
            Remove-Item -LiteralPath $manifest.FullName -Force -ErrorAction SilentlyContinue
            Write-Ok "Removed Ollama manifest $($manifest.FullName.Substring($store.Length).TrimStart('\'))"
        }
    }

    # Blobs are shared by digest. Rebuild the set of digests still referenced by
    # the manifests that remain before deleting anything.
    $stillUsed = @{}
    $targetNames = @{}
    foreach ($manifest in $targets) { $targetNames[$manifest.FullName] = $true }
    foreach ($root in $roots) {
        Get-ChildItem -LiteralPath $root -Recurse -File -ErrorAction SilentlyContinue | ForEach-Object {
            if ($targetNames.ContainsKey($_.FullName)) { return }
            $content = Get-Content -LiteralPath $_.FullName -Raw -ErrorAction SilentlyContinue
            foreach ($digest in (Get-ManifestDigests $content)) { $stillUsed[$digest] = $true }
        }
    }

    $blobRoot = Join-Path $store "blobs"
    $deletedBlobs = 0
    $freedMB = 0
    if (Test-Path -LiteralPath $blobRoot) {
        foreach ($digest in $removedDigests.Keys) {
            if ($stillUsed.ContainsKey($digest)) { continue }
            $hex = $digest.Substring("sha256:".Length)
            $blob = Join-Path $blobRoot "sha256-$hex"
            if (-not (Test-Path -LiteralPath $blob)) { continue }
            if ($DryRun) {
                Write-Info "would remove Ollama blob sha256-$($hex.Substring(0, 8))..."
                continue
            }
            try {
                $size = (Get-Item -LiteralPath $blob).Length
                Remove-Item -LiteralPath $blob -Force -ErrorAction Stop
                $deletedBlobs++
                $freedMB += $size / 1MB
            } catch {
                Write-Warn "Could not remove $blob : $($_.Exception.Message)"
            }
        }
    }
    if (-not $DryRun) {
        Write-Ok "Removed phi3:mini / all-minilm from $store ($deletedBlobs blobs, $([math]::Round($freedMB, 1)) MB)"
    }
}

function Invoke-IdfaUninstall {
    Write-Host "============================================================" -ForegroundColor Green
    Write-Host " IDFA - uninstall" -ForegroundColor Green
    Write-Host "============================================================" -ForegroundColor Green
    Write-Host "Project: $ProjectDir"

    $config = Get-AppConfig
    $dataDir = $null
    if ($null -ne $config) { $dataDir = $config.data_dir }

    $cacheDirs = @(Find-CacheDirs)
    $cacheMB = 0
    foreach ($cache in $cacheDirs) { $cacheMB += (Get-PathSizeMB $cache) }

    Write-Host ""
    Write-Host "Will remove:" -ForegroundColor Cyan
    $labels = @()
    if (Test-Path $VenvDir) { $labels += "Python environment (.venv, $(Get-PathSizeMB $VenvDir) MB)" }
    if (Test-Path $ToolsDir) { $labels += "Qdrant and bundled Ollama (tools\, $(Get-PathSizeMB $ToolsDir) MB)" }
    if ($cacheDirs.Count -gt 0) { $labels += "$($cacheDirs.Count) generated cache folder(s) ($([math]::Round($cacheMB, 1)) MB)" }
    $labels += "Desktop/Start Menu shortcuts"
    $labels += "PID files in $RunDir"
    if ($RemoveModels) { $labels += "phi3:mini and all-minilm from the Ollama store" }
    if ($RemoveBundle) { $labels += "offline bundle (packages\, models\)" }
    if ($PurgeData) { $labels += "CASE DATA in $dataDir and the IDFA configuration" }
    foreach ($label in $labels) { Write-Host "  - $label" -ForegroundColor Gray }

    Write-Host ""
    Write-Host "Kept unless you use -PurgeData / -RemoveBundle:" -ForegroundColor Cyan
    Write-Host "  - source code, README and launcher scripts" -ForegroundColor Gray
    Write-Host "  - case database and evidence" -ForegroundColor Gray
    if (-not $RemoveBundle) { Write-Host "  - packages\ and models\ (they make the next setup work offline)" -ForegroundColor Gray }
    if ($dataDir) { Write-Host "  - data folder: $dataDir" -ForegroundColor Gray }

    if ($DryRun) {
        Write-Host ""
        Write-Info "Dry run: nothing will be changed."
    } elseif (-not $Yes) {
        Write-Host ""
        $answer = Read-Host "Uninstall IDFA from this computer? [y/N]"
        if (-not ($answer -match "^(?i)y")) {
            Write-Warn "Uninstall cancelled; nothing changed."
            return 0
        }
    }

    if ($PurgeData) {
        if (-not (Test-SafeDataPath $dataDir)) {
            Write-Fail "Refusing to delete '$dataDir' as case data: it is a drive root, the project folder, your profile or one of their parents."
            Write-Host "Remove that folder manually if it really is IDFA's data folder." -ForegroundColor Yellow
            return 1
        }
        $details = ""
        if (Test-Path -LiteralPath $dataDir) { $details = " ($(Get-PathSizeMB $dataDir) MB)" }
        Write-Warn "This permanently deletes the case database, evidence copies, logs and Qdrant vectors in $dataDir$details."
        if (-not $DryRun) {
            $typed = Read-Host "Type DELETE to confirm (anything else cancels)"
            if ($typed -cne "DELETE") {
                Write-Warn "Purge cancelled; the runtime is still uninstalled but case data was kept."
                $PurgeData = $false
            }
        }
    }

    $gui = @(Get-RunningGui)
    if ($gui.Count -gt 0 -and -not $DryRun) {
        Write-Warn "IDFA is running (pid $($gui[0].ProcessId)). Close the window so its files can be removed."
        if (-not $Yes) {
            $answer = Read-Host "Close IDFA now and continue? [Y/n]"
            if ($answer -match "^(?i)n") {
                Write-Warn "Uninstall cancelled; close IDFA and run UNINSTALL_IDFA.bat again."
                return 1
            }
        }
        foreach ($process in $gui) {
            Stop-Process -Id $process.ProcessId -Force -ErrorAction SilentlyContinue
        }
        Start-Sleep -Milliseconds 800
    }

    if (-not $DryRun) {
        Write-Step "Stopping services"
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "stop_idfa.ps1") | Out-Host
        if ($LASTEXITCODE -ne 0) {
            Write-Warn "The stop script reported a problem; continuing with the removal."
        }
    }

    Write-Step "Shortcuts"
    if ($DryRun) {
        Write-Info "would remove the IDFA shortcuts"
    } else {
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "install_shortcuts.ps1") -Remove -Quiet | Out-Host
        if ($LASTEXITCODE -eq 0) { Write-Ok "Shortcuts removed" } else { Write-Warn "Shortcuts could not be removed completely" }
    }

    Write-Step "Runtime files"
    Remove-Target $VenvDir "Python environment"
    Remove-Target $ToolsDir "Qdrant and bundled Ollama"
    foreach ($cache in $cacheDirs) {
        Remove-Target $cache "cache folder"
    }
    if (-not $DryRun) {
        Remove-PidFile "worker"
        Remove-PidFile "qdrant"
        Remove-PidFile "ollama-idfa"
        Remove-PidFile "ollama-bundled"
        if (Test-Path $RunDir) { Remove-Item -LiteralPath $RunDir -Recurse -Force -ErrorAction SilentlyContinue }
        Remove-EmptyDir (Split-Path $RunDir -Parent)
    }

    if ($RemoveModels) {
        Write-Step "Ollama models"
        Remove-ImportedModels
    }

    if ($RemoveBundle) {
        Write-Step "Offline bundle"
        Remove-Target (Join-Path $ProjectDir "packages") "offline package cache"
        Remove-Target (Join-Path $ProjectDir "models") "bundled model weights"
    }

    if ($PurgeData) {
        Write-Step "Case data"
        if (Test-Path -LiteralPath $dataDir) {
            Remove-Target $dataDir "case data folder"
        } else {
            Write-Info "Data folder $dataDir does not exist"
        }
        if (Test-Path $ConfigFile) {
            if ($DryRun) {
                Write-Info "would remove $ConfigFile"
            } else {
                Remove-Item -LiteralPath $ConfigFile -Force -ErrorAction SilentlyContinue
                Write-Ok "Removed configuration $ConfigFile"
            }
        }
        if (-not $DryRun) {
            Remove-EmptyDir (Split-Path $ConfigFile -Parent)
        }
    }

    Write-Host ""
    if ($DryRun) {
        Write-Host "Dry run finished. Run UNINSTALL_IDFA.bat without -DryRun to apply." -ForegroundColor Green
        return 0
    }
    if ($script:Failures -gt 0) {
        Write-Fail "$($script:Failures) item(s) could not be removed (a file is probably still open)."
        Write-Host "Close IDFA, then run UNINSTALL_IDFA.bat again." -ForegroundColor Yellow
        return 1
    }
    Write-Host "============================================================" -ForegroundColor Green
    Write-Host " IDFA has been uninstalled." -ForegroundColor Green
    if ($PurgeData) {
        Write-Host " Case data and configuration were deleted." -ForegroundColor Green
    } else {
        Write-Host " Source code and case data were kept." -ForegroundColor Green
    }
    Write-Host " Delete this folder to remove the source code as well." -ForegroundColor Green
    Write-Host "============================================================" -ForegroundColor Green
    return 0
}

exit (Invoke-IdfaUninstall)
