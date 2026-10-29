# Creates (or removes) the IDFA shortcuts, per user and without administrator
# rights. SETUP_IDFA.bat runs this automatically after a successful install, so
# a normal user never has to find START_IDFA.bat inside the project folder.
#
#   powershell -File scripts\install_shortcuts.ps1
#   powershell -File scripts\install_shortcuts.ps1 -Remove
#
param(
    [switch]$Remove,
    [switch]$Quiet
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "_common.ps1")

$StartMenuDir = Join-Path ([Environment]::GetFolderPath("Programs")) "IDFA"
$DesktopDir = [Environment]::GetFolderPath("Desktop")

$Links = @(
    @{
        Name = "IDFA"
        Target = (Join-Path $ProjectDir "START_IDFA.bat")
        Description = "Start IDFA (services + investigator interface)"
        Desktop = $true
    },
    @{
        Name = "Stop IDFA"
        Target = (Join-Path $ProjectDir "STOP_IDFA.bat")
        Description = "Stop the IDFA background services"
        Desktop = $false
    }
)

function Remove-IdfaShortcuts {
    $removed = 0
    foreach ($link in $Links) {
        $startMenuLink = Join-Path $StartMenuDir "$($link.Name).lnk"
        $desktopLink = Join-Path $DesktopDir "$($link.Name).lnk"
        foreach ($path in @($startMenuLink, $desktopLink)) {
            if (Test-Path -LiteralPath $path) {
                Remove-Item -LiteralPath $path -Force
                $removed++
            }
        }
    }
    if ((Test-Path $StartMenuDir) -and -not (Get-ChildItem $StartMenuDir -ErrorAction SilentlyContinue)) {
        Remove-Item -LiteralPath $StartMenuDir -Force
    }
    return $removed
}

if ($Remove) {
    $removed = Remove-IdfaShortcuts
    if (-not $Quiet) {
        if ($removed -gt 0) { Write-Ok "Removed $removed shortcut(s)" }
        else { Write-Info "No IDFA shortcuts were installed" }
    }
    exit 0
}

if (-not (Test-Path (Join-Path $ProjectDir "START_IDFA.bat"))) {
    Write-Fail "START_IDFA.bat is missing from $ProjectDir"
    exit 1
}

New-Item -ItemType Directory -Path $StartMenuDir -Force | Out-Null

$shell = New-Object -ComObject WScript.Shell
try {
    foreach ($link in $Links) {
        $targets = @((Join-Path $StartMenuDir "$($link.Name).lnk"))
        if ($link.Desktop) {
            $targets += (Join-Path $DesktopDir "$($link.Name).lnk")
        }
        foreach ($path in $targets) {
            try {
                $shortcut = $shell.CreateShortcut($path)
                $shortcut.TargetPath = $link.Target
                $shortcut.WorkingDirectory = $ProjectDir
                $shortcut.Description = $link.Description
                $shortcut.Save()
            } catch {
                Write-Warn "Could not create $path : $($_.Exception.Message)"
            }
        }
    }
} finally {
    [void][System.Runtime.InteropServices.Marshal]::ReleaseComObject($shell)
}

$desktopLink = Join-Path $DesktopDir "IDFA.lnk"
if ((Test-Path $desktopLink) -and -not $Quiet) {
    Write-Ok "Shortcuts installed (Desktop and Start Menu)"
}
exit 0
