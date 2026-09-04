# Build "Spin Cycle.exe": venv -> deps -> icon.ico -> PyInstaller ->
# installer.
#
# Usage: .\build.ps1
# Output: dist\Spin Cycle\Spin Cycle.exe, packaged as an installer
# (dist\Spin Cycle-Windows-Setup.exe)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

# PyInstaller support for brand-new Python versions lags behind CPython
# releases -- prefer 3.11/3.10 (what the container target's Dockerfile
# also uses) over whatever `python` happens to resolve to system-wide.
$python = $null
foreach ($candidate in @("3.11", "3.10")) {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        $probe = & py "-$candidate" -c "print('ok')" 2>$null
        if ($probe -eq "ok") {
            $python = @("py", "-$candidate")
            break
        }
    }
}
if (-not $python) {
    if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
        throw "No Python 3.10/3.11 found (via the 'py' launcher) and no 'python' on PATH."
    }
    $python = @("python")
}
Write-Host "Using $(& $python[0] $python[1..($python.Length-1)] --version)"

if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
    Write-Warning "ffmpeg not found on PATH. yt-dlp needs it to mux separate video/audio streams -- install it with: winget install Gyan.FFmpeg"
}

$venvDir = ".venv-build"
if (-not (Test-Path $venvDir)) {
    & $python[0] $python[1..($python.Length-1)] -m venv $venvDir
}
$venvPython = Join-Path $venvDir "Scripts\python.exe"

& $venvPython -m pip install --upgrade pip | Out-Null
& $venvPython -m pip install -r requirements.txt -r "..\..\app\requirements.txt"

# --- Icon: same isolated-dial-on-wood-background artwork the macOS
# target's generate_icon_source.py produces, written straight to
# icon.ico (gitignored, regenerated every build) via Pillow instead of
# macOS's sips/iconutil pipeline. See generate_icon.py for the crop/mask
# coordinates.
& $venvPython generate_icon.py

if (Test-Path "build") { Remove-Item -Recurse -Force "build" }
if (Test-Path "dist") { Remove-Item -Recurse -Force "dist" }
& $venvPython -m PyInstaller spincycle.spec --distpath dist --workpath build --noconfirm

# The whole app/ dir gets copied verbatim as bundled data (see
# spincycle.spec) -- strip the bits that are meaningless inside a
# packaged build, same as build.sh does for the macOS .app.
$bundledApp = Get-ChildItem -Path "dist\Spin Cycle" -Recurse -Directory -Filter "app" | Select-Object -First 1
if ($bundledApp) {
    Get-ChildItem -Path $bundledApp.FullName -Recurse -Directory -Filter "__pycache__" |
        Remove-Item -Recurse -Force
    Remove-Item -Force -ErrorAction SilentlyContinue (Join-Path $bundledApp.FullName "Dockerfile")
    Remove-Item -Force -ErrorAction SilentlyContinue (Join-Path $bundledApp.FullName ".dockerignore")
}

# --- Installer: Inno Setup wraps the whole onedir output (exe +
# _internal) into a normal Program-Files installer with a Start Menu
# entry and an Add/Remove Programs uninstaller -- see installer.iss.
$iscc = Get-Command iscc -ErrorAction SilentlyContinue
if (-not $iscc) {
    $fallback = "${Env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
    if (Test-Path $fallback) { $iscc = $fallback }
}
if (-not $iscc) {
    throw "Inno Setup (ISCC.exe) not found -- install it: winget install JRSoftware.InnoSetup"
}
& $iscc installer.iss

Write-Host ""
Write-Host "Built: $PSScriptRoot\dist\Spin Cycle\Spin Cycle.exe"
Write-Host "Installer: $PSScriptRoot\dist\Spin Cycle-Windows-Setup.exe"
Write-Host "Run it: & 'dist\Spin Cycle\Spin Cycle.exe'"
