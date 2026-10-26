@echo off
setlocal
cd /d "%~dp0"
if not exist "dist\current.txt" goto legacy
set /p "BATCHQR_EXE="<"dist\current.txt"
if not exist "%BATCHQR_EXE%" goto legacy
start "" "%BATCHQR_EXE%"
exit /b 0
:legacy
if exist "dist\BatchQRScan\BatchQRScan.exe" (
    start "" "dist\BatchQRScan\BatchQRScan.exe"
) else (
    ".venv\Scripts\pythonw.exe" app.py
)
