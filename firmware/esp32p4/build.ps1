param([switch]$Flash, [string]$Port = 'COM20')
$ErrorActionPreference = 'Stop'
if (-not $env:IDF_PATH) { $env:IDF_PATH = 'C:\Espressif\frameworks\esp-idf-v5.5.4' }
if (-not $env:IDF_TOOLS_PATH) { $env:IDF_TOOLS_PATH = 'C:\Espressif' }
$venv = Get-ChildItem "$env:IDF_TOOLS_PATH\python_env" -Directory | Where-Object { $_.Name -like 'idf5.5_py*' } | Select-Object -First 1
if (-not $venv) { throw "no idf5.5 python env under $env:IDF_TOOLS_PATH\python_env" }
$py = Join-Path $venv.FullName 'Scripts\python.exe'
$env:IDF_PYTHON_ENV_PATH = $venv.FullName
foreach ($line in (& $py "$env:IDF_PATH\tools\idf_tools.py" export --format key-value)) {
    if ($line -match '^([A-Z_]+)=(.*)$') { Set-Item -Path "env:$($Matches[1])" -Value ($Matches[2] -replace '%PATH%', $env:PATH) }
}
$env:PATH = "$(Join-Path $venv.FullName 'Scripts');$env:IDF_PATH\tools;$env:PATH"
Set-Location $PSScriptRoot
$idf = "$env:IDF_PATH\tools\idf.py"
if ($Flash) {
    & $py $idf -p $Port -b 921600 flash
} else {
    if (-not (Test-Path sdkconfig)) { & $py $idf set-target esp32p4 }
    & $py $idf build
}
exit $LASTEXITCODE
