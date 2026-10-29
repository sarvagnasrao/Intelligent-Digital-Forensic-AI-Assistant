param(
    [switch]$Offline,
    [switch]$SkipModels,
    [switch]$SkipQdrant,
    [switch]$Check,
    [switch]$Repair,
    [switch]$NoShortcuts,
    [switch]$Yes
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "_common.ps1")

$QdrantVersion = "1.20.0"
$QdrantUrl = "https://github.com/qdrant/qdrant/releases/download/v$QdrantVersion/qdrant-x86_64-pc-windows-msvc.zip"

function Test-PythonVersion([string]$Exe) {
    & $Exe -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)" 2>$null
    return $LASTEXITCODE -eq 0
}

function Find-Python {
    # Return a usable Python 3.12 command, or $null when there is none.
    if (Get-Command py -ErrorAction SilentlyContinue) { return "py" }
    if (Get-Command python -ErrorAction SilentlyContinue) { return "python" }
    # A silent install performed by this script is not on PATH yet.
    $candidates = @(
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"),
        (Join-Path $env:ProgramFiles "Python312\python.exe")
    )
    foreach ($candidate in $candidates) {
        if (Test-Path $candidate) { return $candidate }
    }
    return $null
}

function Install-BundledPython {
    # Install Python from packages\python-*-amd64.exe when it is bundled.
    $installer = Get-ChildItem -Path $PackagesDir -Filter "python-*-amd64.exe" -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if (-not $installer) { return $false }

    Write-Host "Installing Python from the offline bundle ($($installer.Name)) ..."
    Start-Process -FilePath $installer.FullName -Wait -ArgumentList @(
        "/quiet", "InstallAllUsers=0", "PrependPath=1", "Include_launcher=1",
        "Include_test=0", "Include_tcltk=0"
    )
    return $true
}

function New-VirtualEnvironment {
    if (Test-Path $VenvPython) {
        if (-not (Test-PythonVersion $VenvPython)) {
            throw "The existing .venv uses Python older than 3.12. Delete $VenvDir and run setup again."
        }
        Write-Ok "Python environment already exists"
        return
    }

    $python = Find-Python
    if (-not $python) {
        if (Install-BundledPython) {
            $python = Find-Python
        }
    }

    Write-Host "Creating .venv ..."
    $created = $false
    if ($python -eq "py") {
        & py -3.12 -m venv $VenvDir
        $created = ($LASTEXITCODE -eq 0)
        if (-not $created) {
            & py -3 -m venv $VenvDir
            $created = ($LASTEXITCODE -eq 0)
        }
    } elseif ($python) {
        & $python -m venv $VenvDir
        $created = ($LASTEXITCODE -eq 0)
    }

    if (-not $created) {
        throw "Python 3.12+ was not found. Install it from https://www.python.org/downloads/windows/ (or place python-3.12.10-amd64.exe in packages\) and run SETUP_IDFA.bat again."
    }

    if (-not (Test-PythonVersion $VenvPython)) {
        throw "The new environment does not report Python 3.12 or newer."
    }
    Write-Ok "Created $VenvDir"
}

function Install-PythonPackages {
    $manifest = Join-Path $PackagesDir "offline-manifest.json"
    $useCache = (Test-Path $manifest) -or $Offline

    if ($useCache) {
        if (-not (Test-Path $PackagesDir)) {
            throw "Offline package folder not found: $PackagesDir"
        }
        Write-Host "Installing Python packages from the local cache ..."
        & powershell.exe -NoProfile -ExecutionPolicy Bypass `
            -File (Join-Path $PSScriptRoot "install_from_local.ps1")
        if ($LASTEXITCODE -eq 0) {
            Write-Ok "Python packages installed from the local cache"
            return
        }
        if ($Offline) {
            throw "The local package cache is incomplete. Rebuild it on a connected machine or run setup without -Offline."
        }
        Write-Warn "Local cache could not satisfy every package; using the network instead."
    }

    Write-Host "Installing Python packages from requirements.txt ..."
    & $VenvPython -m pip install --upgrade pip --quiet
    Push-Location $ProjectDir
    try {
        & $VenvPython -m pip install -r requirements.txt
    } finally {
        Pop-Location
    }
    if ($LASTEXITCODE -ne 0) {
        throw "Python package installation failed."
    }
    Write-Ok "Python packages installed"
}

function Install-Qdrant {
    if (Test-Path $QdrantExe) {
        Write-Ok "Qdrant already present"
        return
    }
    if ($SkipQdrant) {
        Write-Warn "Skipping Qdrant; semantic search will be unavailable."
        return
    }

    $archive = Get-ChildItem -Path $PackagesDir -Filter "qdrant-*windows*.zip" -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if (-not $archive) {
        $archive = Get-ChildItem -Path $ProjectDir -Filter "qdrant-*windows*.zip" -ErrorAction SilentlyContinue |
            Select-Object -First 1
    }

    if (-not $archive) {
        if ($Offline) {
            Write-Warn "Qdrant is not bundled. Place qdrant-x86_64-pc-windows-msvc.zip in packages\ or tools\."
            return
        }
        $target = Join-Path $env:TEMP "qdrant-$QdrantVersion-windows.zip"
        Write-Host "Downloading Qdrant $QdrantVersion ..."
        if (-not (Get-RemoteFile $QdrantUrl $target)) {
            Write-Warn "Could not download Qdrant."
            Write-Host "  Download it manually from https://github.com/qdrant/qdrant/releases" -ForegroundColor Gray
            return
        }
        $archive = Get-Item $target
    }

    Write-Host "Installing Qdrant into $ToolsDir\qdrant ..."
    New-Item -ItemType Directory -Path (Join-Path $ToolsDir "qdrant") -Force | Out-Null
    Expand-Archive -Path $archive.FullName -DestinationPath (Join-Path $ToolsDir "qdrant") -Force
    if (-not (Test-Path $QdrantExe)) {
        $found = Get-ChildItem -Path $ToolsDir -Recurse -Filter "qdrant.exe" -ErrorAction SilentlyContinue |
            Select-Object -First 1
        if ($found) {
            Copy-Item -Path $found.FullName -Destination $QdrantExe -Force
        }
    }
    if (Test-Path $QdrantExe) {
        Write-Ok "Qdrant installed at $QdrantExe"
    } else {
        Write-Warn "Qdrant archive extracted, but qdrant.exe was not found."
    }
}

function Start-OllamaService([string]$HostUrl) {
    if (Test-HttpOk "$HostUrl/api/tags" 3) { return $true }
    $exe = Find-Ollama
    if (-not $exe) { return $false }
    Set-OllamaBind $HostUrl
    $process = Start-Process -FilePath $exe -ArgumentList "serve" -WindowStyle Hidden -PassThru
    if (Test-BundledRuntime $exe) { Save-PidFile "ollama-bundled" $process.Id }
    for ($attempt = 0; $attempt -lt 40; $attempt++) {
        if (Test-HttpOk "$HostUrl/api/tags" 2) { return $true }
        Start-Sleep -Milliseconds 500
    }
    return $false
}

function Install-Ollama {
    $exe = Find-Ollama
    if ($exe) {
        Write-Ok "Ollama already available at $exe"
        return $exe
    }

    # The bundle carries the CPU runtime rather than the full installer: it is
    # 25 MB instead of 1.6 GB and needs no administrator rights. GPU
    # acceleration additionally requires the official installer.
    $runtime = Join-Path $PackagesDir "ollama-windows-cpu.zip"
    if ((Test-Path $runtime) -and ((Get-Item $runtime).Length -gt 5MB)) {
        Write-Host "Installing the bundled Ollama runtime into $ToolsDir\ollama ..."
        New-Item -ItemType Directory -Path (Join-Path $ToolsDir "ollama") -Force | Out-Null
        Expand-Archive -Path $runtime -DestinationPath (Join-Path $ToolsDir "ollama") -Force
        $exe = Find-Ollama
        if ($exe) {
            Write-Ok "Ollama runtime installed (CPU)"
            return $exe
        }
    }

    $installer = Join-Path $PackagesDir "OllamaSetup.exe"
    if ((Test-Path $installer) -and ((Get-Item $installer).Length -gt 1GB)) {
        Write-Host "Installing Ollama from the offline bundle ..."
        Start-Process -FilePath $installer `
            -ArgumentList "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART" -Wait
        $exe = Find-Ollama
        if ($exe) {
            Write-Ok "Ollama installed"
            return $exe
        }
    }

    Write-Warn "Ollama is not installed."
    Write-Host "  Install it from https://ollama.com/download/windows, then run SETUP_IDFA.bat again." -ForegroundColor Gray
    Write-Host "  The application still works without it: keyword search and examination do not need Ollama." -ForegroundColor Gray
    return $null
}

function Import-BundledModels {
    $source = Join-Path $ProjectDir "models\ollama"
    if (-not (Test-Path (Join-Path $source "manifests"))) { return $false }

    $destination = $env:OLLAMA_MODELS
    if (-not $destination) {
        $destination = Join-Path $env:USERPROFILE ".ollama\models"
    }
    New-Item -ItemType Directory -Path $destination -Force | Out-Null

    # Large Ollama layers are split into Git LFS-sized chunks in the repository.
    # Reassemble those directly in the user's model store, never in the checkout.
    $partGroups = Get-ChildItem -Path $source -Recurse -File |
        Where-Object { $_.Name -match '\.part\d{4}$' } |
        Group-Object { $_.FullName -replace '\.part\d{4}$', '' }
    foreach ($group in $partGroups) {
        $first = $group.Group | Sort-Object Name | Select-Object -First 1
        $relative = $first.FullName.Substring($source.Length).TrimStart('\') -replace '\.part\d{4}$', ''
        $target = Join-Path $destination $relative
        $expectedLength = ($group.Group | Measure-Object -Property Length -Sum).Sum
        if ((Test-Path -LiteralPath $target) -and (Get-Item -LiteralPath $target).Length -eq $expectedLength) {
            continue
        }
        $parent = Split-Path $target -Parent
        if (-not (Test-Path -LiteralPath $parent)) {
            New-Item -ItemType Directory -Path $parent -Force | Out-Null
        }
        $temporary = "$target.idfa-part"
        try {
            $output = [System.IO.File]::Open($temporary, [System.IO.FileMode]::Create,
                [System.IO.FileAccess]::Write, [System.IO.FileShare]::None)
            try {
                foreach ($part in ($group.Group | Sort-Object Name)) {
                    $chunkStream = [System.IO.File]::OpenRead($part.FullName)
                    try { $chunkStream.CopyTo($output) } finally { $chunkStream.Dispose() }
                }
            } finally { $output.Dispose() }
            if ((Get-Item -LiteralPath $temporary).Length -ne $expectedLength) {
                throw "Reassembled model layer has an unexpected size: $relative"
            }
            Move-Item -LiteralPath $temporary -Destination $target -Force
        } finally {
            if (Test-Path -LiteralPath $temporary) {
                Remove-Item -LiteralPath $temporary -Force -ErrorAction SilentlyContinue
            }
        }
    }

    # Only copy what is missing. A full copy is over 2 GB, and the second setup
    # run should not rewrite the whole store just to confirm it is there.
    $copied = 0
    $skipped = 0
    Get-ChildItem -Path $source -Recurse -File |
        Where-Object { $_.Name -notmatch '\.part\d{4}$' } | ForEach-Object {
        $relative = $_.FullName.Substring($source.Length).TrimStart('\')
        $target = Join-Path $destination $relative
        if ((Test-Path $target) -and ((Get-Item $target).Length -eq $_.Length)) {
            $skipped++
            return
        }
        $parent = Split-Path $target -Parent
        if (-not (Test-Path $parent)) {
            New-Item -ItemType Directory -Path $parent -Force | Out-Null
        }
        Copy-Item -Path $_.FullName -Destination $target -Force
        $copied++
    }

    if ($copied -gt 0) {
        Write-Ok "Bundled models imported into $destination ($copied files copied)"
    } else {
        Write-Ok "Bundled models already in $destination"
    }
    return $true
}

function Ensure-Model([string]$HostUrl, [string]$Model, [string]$OllamaExe, [switch]$NoPull) {
    $tags = Get-Json "$HostUrl/api/tags" 5
    if ($null -eq $tags) {
        Write-Warn "Ollama is not responding; cannot check $Model"
        return
    }
    $names = @($tags.models | ForEach-Object { $_.name })
    $present = $names | Where-Object { $_ -eq $Model -or $_ -like "${Model}:*" }
    if ($present) {
        Write-Ok "$Model is available"
        return
    }
    if ($NoPull -or -not $OllamaExe) {
        Write-Warn "$Model is missing"
        Write-Host "  Import models\ollama, or pull it once on a connected machine." -ForegroundColor Gray
        return
    }

    Write-Host "Pulling $Model ..."
    & $OllamaExe pull $Model
    if ($LASTEXITCODE -eq 0) {
        Write-Ok "$Model pulled"
    } else {
        Write-Warn "Could not pull $Model. On an offline machine, import the bundled models instead."
    }
}

function Initialize-Database {
    if (-not (Test-Path $ConfigFile)) {
        Write-Host "No configuration yet; the database is created on the first GUI launch." -ForegroundColor Gray
        return
    }

    Write-Host "Applying database migrations ..."
    Push-Location $ProjectDir
    try {
        & $VenvPython -m alembic upgrade head
        if ($LASTEXITCODE -ne 0) {
            Write-Warn "The database has no migration history yet; recording the current schema."
            $code = "from app.db import load_all_models; load_all_models(); from app.db.session import init_db; init_db()"
            & $VenvPython -c $code
            if ($LASTEXITCODE -ne 0) {
                throw "Could not initialise the database."
            }
            & $VenvPython -m alembic upgrade head
            if ($LASTEXITCODE -ne 0) {
                throw "Database migrations failed."
            }
        }
    } finally {
        Pop-Location
    }
    Write-Ok "Database is up to date"
}

function Test-Module([string]$Name) {
    & $VenvPython -c "import $Name" 2>$null
    return $LASTEXITCODE -eq 0
}

function Invoke-Preflight($Config) {
    # A friendly summary of everything setup depends on, printed before any work
    # starts. It never changes the machine, so ``-Check`` can run it alone.
    Write-Step "Checking this computer"
    $warnings = 0
    $failures = 0

    $version = [Environment]::OSVersion.Version
    if ([Environment]::Is64BitOperatingSystem) {
        Write-Ok "Windows $($version.Major).$($version.Minor) build $($version.Build), 64-bit"
    } else {
        Write-Fail "A 64-bit Windows installation is required."
        $failures++
    }

    $bundle = Get-BundleInfo
    $python = Find-Python
    if (Test-Path $VenvPython) {
        Write-Ok "Python environment already prepared at $VenvDir"
    } elseif ($python) {
        $label = if ($python -eq "py") { "the py launcher" } else { $python }
        Write-Ok "Python found: $label"
    } elseif ($bundle.Python) {
        Write-Ok "Python will be installed from the bundled installer"
    } else {
        Write-Warn "Python 3.12 was not found and no installer is bundled."
        $warnings++
    }

    $projectFree = Get-FreeSpaceGB $ProjectDir
    if ($null -ne $projectFree) {
        if ($projectFree -lt 2) {
            Write-Fail "Only $projectFree GB free on the project drive; setup needs at least 2 GB."
            $failures++
        } elseif ($projectFree -lt 6) {
            Write-Warn "$projectFree GB free on the project drive; setup can use about 6 GB."
            $warnings++
        } else {
            Write-Ok "$projectFree GB free on the project drive"
        }
    }

    if ($null -ne $Config -and $Config.data_dir) {
        $dataFree = Get-FreeSpaceGB $Config.data_dir
        if ($null -ne $dataFree) {
            if ($dataFree -lt 10) {
                Write-Warn "$dataFree GB free in the data folder; case images need room."
                $warnings++
            } else {
                Write-Ok "$dataFree GB free in the data folder"
            }
        }
    }

    if ($bundle.Manifest -and $bundle.Wheels -gt 0) {
        $parts = @("$($bundle.Wheels) Python wheels")
        if ($bundle.Qdrant) { $parts += "Qdrant" }
        if ($bundle.Ollama) { $parts += "Ollama runtime" }
        if ($bundle.Python) { $parts += "Python installer" }
        Write-Ok ("Offline bundle found: " + ($parts -join ", "))
        if ($bundle.ManifestWheels -gt 0 -and $bundle.ManifestWheels -ne $bundle.Wheels) {
            Write-Warn "The bundle manifest lists $($bundle.ManifestWheels) wheels but $($bundle.Wheels) are present; rebuild it with scripts\build_offline_bundle.ps1."
            $warnings++
        }
        if ($bundle.ManifestWheelBytes -gt 0 -and
            $bundle.WheelBytes -lt ($bundle.ManifestWheelBytes * 0.95)) {
            Write-Fail "The package cache is incomplete ($($bundle.WheelGB) GB of bundled wheels). Run 'git lfs pull' from the project folder, then retry setup."
            $failures++
        }
        if ($bundle.Models) {
            Write-Ok "Bundled model weights: $($bundle.ModelGB) GB"
            if ($bundle.ManifestModelGB -gt 0 -and $bundle.ModelGB -lt ($bundle.ManifestModelGB * 0.95)) {
                Write-Fail "Only $($bundle.ModelGB) GB of the $($bundle.ManifestModelGB) GB of bundled model files are present. Run 'git lfs pull' from the project folder, then retry setup."
                $failures++
            }
        } else {
            Write-Info "No model weights bundled; the AI models are pulled from Ollama unless already present."
        }
    } else {
        Write-Info "No offline bundle: setup downloads the Python packages and tools (~250 MB)."
        if (Test-HttpOk "https://pypi.org/simple/pip/" 5) {
            Write-Ok "Internet reachable for the download"
        } else {
            Write-Warn "No internet and no offline bundle; setup cannot install the packages."
            $warnings++
        }
    }

    $ports = @(
        @{ Name = "Worker"; Port = 8000 },
        @{ Name = "Qdrant"; Port = 6333 },
        @{ Name = "Ollama"; Port = 11434 }
    )
    if ($null -ne $Config) {
        $ports[0].Port = Get-PortFromUrl $Config.worker_url 8000
        $ports[1].Port = Get-PortFromUrl $Config.qdrant_url 6333
        $ports[2].Port = Get-PortFromUrl $Config.ollama_host 11434
    }
    foreach ($entry in $ports) {
        $owner = Get-PortOwner $entry.Port
        if ($owner) {
            Write-Info "$($entry.Name) port $($entry.Port) is already in use by $(Format-Process $owner); IDFA may already be running."
        }
    }

    Write-Host ""
    if ($failures -gt 0) {
        Write-Fail "$failures problem(s) must be fixed before setup can continue."
    } elseif ($warnings -gt 0) {
        Write-Warn "$warnings warning(s); setup can continue."
    } else {
        Write-Ok "This computer has everything setup needs."
    }
    return ($failures -eq 0)
}

function Invoke-Doctor {
    Write-Step "Verifying the installation"
    $modules = @(
        @{ Name = "PySide6"; Label = "GUI toolkit" },
        @{ Name = "sqlalchemy"; Label = "Database ORM" },
        @{ Name = "alembic"; Label = "Migrations" },
        @{ Name = "fastapi"; Label = "Worker API" },
        @{ Name = "pytsk3"; Label = "Disk examination" },
        @{ Name = "pyewf"; Label = "E01 image support" }
    )
    $missing = @()
    foreach ($module in $modules) {
        if (Test-Module $module.Name) {
            Write-Ok "$($module.Label) ($($module.Name))"
        } else {
            Write-Fail "$($module.Label) ($($module.Name)) is missing"
            $missing += $module.Name
        }
    }
    if ($missing -contains "pytsk3" -or $missing -contains "pyewf") {
        Write-Host "  E01 and disk examination need: pip install pytsk3 libewf-python" -ForegroundColor Gray
    }
    if ($missing -contains "pytsk3") {
        Write-Warn "Examination will not work until pytsk3 is installed."
    }

    if (Test-Path $QdrantExe) {
        Write-Ok "Qdrant binary"
    } else {
        Write-Warn "Qdrant is not installed; semantic search will be unavailable."
    }

    $ollama = Find-Ollama
    if ($ollama) {
        Write-Ok "Ollama at $ollama"
    } else {
        Write-Warn "Ollama is not installed; AI replies and semantic search need it."
    }

    & $VenvPython -m pip check 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) {
        Write-Ok "Installed packages are consistent (pip check)"
    } else {
        Write-Warn "pip check reported conflicting packages; run SETUP_IDFA.bat -Repair."
    }

    $bundle = Get-BundleInfo
    if ($bundle.Models) {
        Write-Ok "Bundled model weights ($($bundle.ModelGB) GB)"
    } else {
        Write-Info "No bundled model weights; the AI models come from Ollama"
    }

    if (Test-Path (Join-Path ([Environment]::GetFolderPath("Desktop")) "IDFA.lnk")) {
        Write-Ok "Desktop shortcut"
    } else {
        Write-Info "No desktop shortcut yet (SETUP_IDFA.bat creates it)"
    }

    if (Test-Path $ConfigFile) {
        Write-Ok "Configuration at $ConfigFile"
    } else {
        Write-Info "The first GUI launch asks for a data folder"
    }
}

Write-Host "============================================================" -ForegroundColor Green
Write-Host " IDFA - setup" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
Write-Host "Project: $ProjectDir"

if ($Check) {
    $config = Get-AppConfig
    $preflightOk = Invoke-Preflight $config
    if (-not (Test-Path $VenvPython)) {
        Write-Fail "No Python environment at $VenvPython. Run SETUP_IDFA.bat first."
        exit 1
    }
    Invoke-Doctor
    if (-not $preflightOk) { exit 1 }
    exit 0
}

if ($Repair) {
    Write-Step "Repair"
    if (Test-Path $VenvDir) {
        $confirmed = [bool]$Yes
        if (-not $confirmed) {
            $answer = Read-Host "Delete $VenvDir and reinstall every Python package? [y/N]"
            $confirmed = ($answer -match "^(?i)y")
        }
        if (-not $confirmed) {
            Write-Warn "Repair cancelled; nothing changed."
            exit 0
        }
        Remove-Item -LiteralPath $VenvDir -Recurse -Force
        Write-Ok "Removed $VenvDir"
    } else {
        Write-Info "There is no Python environment to remove"
    }
}

$preflightConfig = Get-AppConfig
$preflightOk = Invoke-Preflight $preflightConfig
if (-not $preflightOk) {
    Write-Host "Fix the problems above, then run SETUP_IDFA.bat again." -ForegroundColor Yellow
    exit 1
}

Write-Step "Python environment"
$pythonCommand = Find-Python
if ($pythonCommand) {
    Write-Host "Using: $pythonCommand"
} else {
    $bundled = Get-ChildItem -Path $PackagesDir -Filter "python-*-amd64.exe" -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($bundled) {
        Write-Host "Using the bundled installer: $($bundled.Name)"
    } else {
        Write-Warn "Python 3.12 was not found and no installer is bundled."
        Write-Host "  Install it from https://www.python.org/downloads/windows/, then run SETUP_IDFA.bat again." -ForegroundColor Gray
    }
}
New-VirtualEnvironment

Write-Step "Python packages"
Install-PythonPackages

# Read the configuration only once the environment exists, so the launcher can
# reuse the application's own loader instead of parsing YAML itself.
$config = Get-AppConfig

Write-Step "Forensic tools"
Install-Qdrant

Write-Step "Ollama"
$ollamaExe = Install-Ollama

Write-Step "AI models"
if ($SkipModels) {
    Write-Warn "Skipping model checks (-SkipModels)."
} else {
    $modelHost = "http://127.0.0.1:11434"
    if ($null -ne $config -and $config.ollama_host) { $modelHost = $config.ollama_host }

    if (Import-BundledModels) {
        Write-Ok "Models were imported from the offline bundle"
    }

    if (Start-OllamaService $modelHost) {
        $chatModel = "phi3:mini"
        $embeddingModel = "all-minilm"
        if ($null -ne $config) {
            if ($config.ollama_model) { $chatModel = $config.ollama_model }
            if ($config.embedding_model) { $embeddingModel = $config.embedding_model }
        }
        Ensure-Model $modelHost $chatModel $ollamaExe -NoPull:$Offline
        Ensure-Model $modelHost $embeddingModel $ollamaExe -NoPull:$Offline
    } else {
        Write-Warn "Ollama is not responding, so models could not be checked."
    }
}

Write-Step "Database"
Initialize-Database

Invoke-Doctor

if ($NoShortcuts) {
    Write-Info "Skipping shortcuts (-NoShortcuts)"
} else {
    Write-Step "Shortcuts"
    & powershell.exe -NoProfile -ExecutionPolicy Bypass `
        -File (Join-Path $PSScriptRoot "install_shortcuts.ps1") -Quiet
    if ($LASTEXITCODE -eq 0) {
        Write-Ok "Desktop and Start Menu shortcuts created"
    } else {
        Write-Warn "Shortcuts were not created; start the app with START_IDFA.bat."
    }
}

Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host " Setup complete." -ForegroundColor Green
Write-Host " Start the application from the IDFA shortcut or START_IDFA.bat" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
