@echo off
rem Mo trang web review nhan:  review_web   (may khac cung mang vao: review_web --lan)
setlocal
set "HERE=%~dp0"
set "PY="
for %%V in ("%HERE%venv" "%HERE%..\venv") do if not defined PY if exist "%%~V\Scripts\python.exe" set "PY=%%~V\Scripts\python.exe"
set PYTHONIOENCODING=utf-8
if not defined PY (
    echo Chua co venv. Chay: cd /d "%HERE%" ^&^& python -m venv venv ^&^& venv\Scripts\pip install -r requirements.txt
    exit /b 1
)
"%PY%" "%HERE%review_web.py" %*
exit /b %ERRORLEVEL%
