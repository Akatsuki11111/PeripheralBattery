$ErrorActionPreference = 'Stop'
$originalPath = $env:PATH
Push-Location $PSScriptRoot
try {
    $pythonCommand = (Get-Command python -ErrorAction Stop).Source
    & $pythonCommand -m pip install -r requirements.txt
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
    & $pythonCommand -m pip install pyinstaller==6.22.3
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller installation failed.' }
    $pythonDirectory = & $pythonCommand -c 'import sys; from pathlib import Path; print(Path(sys.executable).parent)'
    # Prevent unrelated tools (e.g. Poppler/Conda) supplying a different ICU DLL.
    $env:PATH = "$pythonDirectory;$env:SystemRoot\System32;$env:SystemRoot"
    & $pythonCommand -m PyInstaller --noconfirm --clean --onefile --windowed --name PeripheralBattery --icon assets/app.ico --version-file version_info.txt --add-data 'assets;assets' --add-data 'catalog.json;.' --collect-submodules battery_backends app.py
    if ($LASTEXITCODE -ne 0) { throw 'Build failed.' }
    Write-Host 'Ready: dist\PeripheralBattery.exe'
} finally {
    $env:PATH = $originalPath
    Pop-Location
}
