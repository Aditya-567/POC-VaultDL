@echo off
echo Building VaultDL.exe...

REM Kill any running instance so PyInstaller can overwrite the EXE
taskkill /F /IM VaultDL.exe >nul 2>&1

REM Build the React frontend first
cd frontend
call npm run build
cd ..

REM Download and stage aria2 + ffmpeg for bundling in the EXE
powershell -ExecutionPolicy Bypass -File scripts\prepare-binaries.ps1
if errorlevel 1 (
	echo Failed to prepare third-party binaries.
	pause
	exit /b 1
)

REM Run PyInstaller using full path (works even if pyinstaller is not on PATH)
"%APPDATA%\Python\Python314\Scripts\pyinstaller.exe" VaultDL.spec --noconfirm

echo.
echo Done! Your app is at: dist\VaultDL.exe
pause
