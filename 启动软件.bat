@echo off
cd /d "%~dp0"
if exist "dist\BatchQRScan\BatchQRScan.exe" (
    start "" "dist\BatchQRScan\BatchQRScan.exe"
) else (
    ".venv\Scripts\pythonw.exe" app.py
)
