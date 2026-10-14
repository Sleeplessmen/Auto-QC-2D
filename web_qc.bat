@echo off
rem Web QC nhan 2D (ban day du):  web_qc        -> http://localhost:8000
rem                                web_qc --lan  -> may khac cung mang vao http://<ip may nay>:8000
setlocal
set "HERE=%~dp0"
set "PY="
for %%V in ("%HERE%venv" "%HERE%..\venv") do if not defined PY if exist "%%~V\Scripts\python.exe" set "PY=%%~V\Scripts\python.exe"
set PYTHONIOENCODING=utf-8
if not defined PY (
    echo Chua co venv. Chay: cd /d "%HERE%" ^&^& python -m venv venv ^&^& venv\Scripts\pip install -r requirements.txt
    exit /b 1
)
"%PY%" "%HERE%web_qc\server.py" %*
exit /b %ERRORLEVEL%
