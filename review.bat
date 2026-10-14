@echo off
rem Review nhan 2D bang lenh:  review --job 57   (xem: review --help)
setlocal
set "HERE=%~dp0"
set "PY="
for %%V in ("%HERE%venv" "%HERE%..\venv") do if not defined PY if exist "%%~V\Scripts\python.exe" set "PY=%%~V\Scripts\python.exe"
set PYTHONIOENCODING=utf-8
if not defined PY (
    echo Chua co venv. Chay: cd /d "%HERE%" ^&^& python -m venv venv ^&^& venv\Scripts\pip install -r requirements.txt
    exit /b 1
)
"%PY%" "%HERE%review.py" %*
exit /b %ERRORLEVEL%
