$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$releaseId = (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + [guid]::NewGuid().ToString('N').Substring(0, 8)
$releaseRoot = Join-Path $PSScriptRoot "dist\releases\$releaseId"
if (Test-Path -LiteralPath $releaseRoot) { throw 'Release directory already exists' }
& .\.venv\Scripts\python.exe -m pytest -q
if ($LASTEXITCODE -ne 0) { throw 'Tests failed' }
& .\.venv\Scripts\python.exe -m PyInstaller --noconfirm --windowed --name BatchQRScan --distpath $releaseRoot --collect-all pypdfium2 --collect-all zxingcpp --collect-all rapidocr_onnxruntime --collect-all uiautomation --collect-submodules comtypes.gen app.py
if ($LASTEXITCODE -ne 0) { throw 'Build failed' }
New-Item -ItemType Directory -Path 'tmp' -Force | Out-Null
$releaseExe = Join-Path $releaseRoot 'BatchQRScan\BatchQRScan.exe'
$runtimeProcess = Start-Process -FilePath $releaseExe -ArgumentList '--check-runtime','tmp/runtime-check.json' -WindowStyle Hidden -Wait -PassThru
if ($runtimeProcess.ExitCode -ne 0) { throw 'Packaged runtime check failed; see tmp/runtime-check.json' }
$relativeExe = "dist\releases\$releaseId\BatchQRScan\BatchQRScan.exe"
Set-Content -LiteralPath 'dist\current.txt.pending' -Value $relativeExe -Encoding ascii
Move-Item -LiteralPath 'dist\current.txt.pending' -Destination 'dist\current.txt' -Force
Write-Host "Ready: $relativeExe"
