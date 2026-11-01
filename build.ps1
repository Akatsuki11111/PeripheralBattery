param([ValidateSet('stable','experimental','both')][string]$Channel='stable')
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
    $channels = if($Channel -eq 'both'){@('stable','experimental')}else{@($Channel)}
    foreach($buildChannel in $channels){
        $env:PB_BUILD_CHANNEL=$buildChannel
        & $pythonCommand -m PyInstaller --noconfirm --clean --distpath "dist/$buildChannel" --workpath "build/$buildChannel" PeripheralBattery.spec
        if ($LASTEXITCODE -ne 0) { throw 'Build failed.' }
        $releaseVersion = if($buildChannel -eq 'stable'){'2.8.0'}else{'2.8.1-experimental.1'}
        $releaseName = "PeripheralBattery-v$releaseVersion.exe"
        Copy-Item -LiteralPath "dist/$buildChannel/PeripheralBattery.exe" -Destination "dist/$releaseName" -Force
        Write-Host "Ready: dist\$releaseName"
    }
} finally {
    $env:PATH = $originalPath
    Remove-Item Env:PB_BUILD_CHANNEL -ErrorAction SilentlyContinue
    Pop-Location
}
