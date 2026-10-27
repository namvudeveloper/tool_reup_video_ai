@echo off
chcp 65001 >nul 2>&1
setlocal EnableDelayedExpansion
title Giao Dien Ghep Video 5 Tieng va Lach Ban Quyen (Windows)

cd /d "%~dp0"

echo ========================================================================
echo   🎬 TOOL GHEP VIDEO 5 TIENG ^& LACH BAN QUYEN ^(GIAO DIEN KEO THA^)
echo ========================================================================
echo.

:: 1. Kiểm tra Python trên Windows
set "PY_CMD="
where python >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    python --version >nul 2>&1
    if !ERRORLEVEL! EQU 0 set "PY_CMD=python"
)

if "%PY_CMD%"=="" (
    where py >nul 2>&1
    if !ERRORLEVEL! EQU 0 (
        py -3 --version >nul 2>&1
        if !ERRORLEVEL! EQU 0 set "PY_CMD=py -3"
    )
)

if "%PY_CMD%"=="" (
    echo [LOI] May tinh chua cai dat Python 3!
    echo 👉 Vui long tai va cai dat Python tai: https://www.python.org/downloads/
    echo    ^(Luu y: Tich chon o "Add python.exe to PATH" khi cai dat^)
    echo.
    pause
    exit /b 1
)

:: 2. Kiểm tra FFmpeg
if exist "%~dp0bin\ffmpeg.exe" (
    set "PATH=%~dp0bin;%PATH%"
)

where ffmpeg >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [CANH BAO] Chua tim thay FFmpeg tren he thong.
    where winget >nul 2>&1
    if !ERRORLEVEL! EQU 0 (
        echo [INFO] Dang tu dong cai dat FFmpeg qua Windows Package Manager ^(winget^)...
        winget install -e --id Gyan.FFmpeg --accept-source-agreements --accept-package-agreements
    ) else (
        echo 👉 Vui long cai FFmpeg bang lenh: winget install Gyan.FFmpeg
        echo    Hoac bo file ffmpeg.exe va ffprobe.exe vao thu muc "bin\" cua tool.
    )
)

:: 3. Khởi tạo môi trường ảo (.venv)
if not exist ".venv\Scripts\python.exe" (
    %PY_CMD% -m venv .venv >nul 2>&1
)

if exist ".venv\Scripts\python.exe" (
    set "VENV_PY=.venv\Scripts\python.exe"
) else (
    set "VENV_PY=%PY_CMD%"
)

if not exist ".venv\.deps_installed" (
    echo [INFO] Dang cai dat thu vien ho tro ^(yt-dlp, rich^)...
    "%VENV_PY%" -m pip install -r requirements.txt -q >nul 2>&1
    if !ERRORLEVEL! EQU 0 (
        echo ok > ".venv\.deps_installed"
    )
)

:: 4. Mở Giao Diện Kéo Thả (GUI) mặc định
if "%~1"=="--cli" (
    shift
    "%VENV_PY%" main.py %1 %2 %3 %4 %5
) else (
    "%VENV_PY%" gui_server.py %*
)

pause
