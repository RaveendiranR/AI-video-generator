@echo off
setlocal
if "%PYTHON_BIN%"=="" set PYTHON_BIN=py
%PYTHON_BIN% -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install -e .
echo.
echo Installed. Activate with: .venv\Scripts\activate
echo Check FFmpeg with: python -m faceless_video_generator --check