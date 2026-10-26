$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
& .\.venv\Scripts\python.exe -m pytest -q
if ($LASTEXITCODE -ne 0) { throw 'Tests failed' }
& .\.venv\Scripts\python.exe -m PyInstaller --noconfirm --windowed --name BatchQRScan --collect-all pypdfium2 --collect-all zxingcpp --collect-all rapidocr_onnxruntime --collect-all uiautomation --collect-submodules comtypes.gen app.py
if ($LASTEXITCODE -ne 0) { throw 'Build failed' }
New-Item -ItemType Directory -Path 'tmp' -Force | Out-Null
$runtimeProcess = Start-Process -FilePath '.\dist\BatchQRScan\BatchQRScan.exe' -ArgumentList '--check-runtime','tmp/runtime-check.json' -WindowStyle Hidden -Wait -PassThru
if ($runtimeProcess.ExitCode -ne 0) { throw 'Packaged runtime check failed; see tmp/runtime-check.json' }
Write-Host 'Ready: dist\BatchQRScan\BatchQRScan.exe'
