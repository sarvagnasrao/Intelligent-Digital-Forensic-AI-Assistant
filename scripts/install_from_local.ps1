# IDFA - install Python packages from the local wheel cache.
#
# Used by setup.ps1 when an offline bundle is present. The cache must contain a
# wheel for every requirement; pip resolves the set with no network access.

$projectDir = Split-Path $PSScriptRoot -Parent
$packagesDir = Join-Path $projectDir "packages"
$venvPython = Join-Path $projectDir ".venv\Scripts\python.exe"
$requirements = Join-Path $projectDir "requirements.txt"

if (-not (Test-Path $venvPython)) {
    Write-Error "Python environment not found: $venvPython"
    exit 1
}
if (-not (Test-Path $packagesDir)) {
    Write-Error "Package directory not found: $packagesDir"
    exit 1
}

$wheelFiles = @(Get-ChildItem $packagesDir -Filter "*.whl" -ErrorAction SilentlyContinue)
if ($wheelFiles.Count -eq 0) {
    Write-Error "No wheels found in $packagesDir"
    exit 1
}

Write-Host "Offline package cache: $packagesDir ($($wheelFiles.Count) wheels)" -ForegroundColor Gray

& $venvPython -m pip install --no-index --find-links $packagesDir --upgrade -r $requirements
if ($LASTEXITCODE -ne 0) {
    Write-Host "Offline installation failed: the cache does not satisfy requirements.txt." -ForegroundColor Red
    exit $LASTEXITCODE
}

Write-Host "Python packages installed from the local cache." -ForegroundColor Green
exit 0
