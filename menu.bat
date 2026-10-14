@echo off
rem Menu chon cong cu gan nhan CVAT (menu.py). Bam dup file nay, hoac go:  menu   /   menu 10842
setlocal
set "HERE=%~dp0"
set "PY="
for %%V in ("%HERE%venv" "%HERE%..\venv") do if not defined PY if exist "%%~V\Scripts\python.exe" set "PY=%%~V\Scripts\python.exe"
set PYTHONIOENCODING=utf-8
chcp 65001 >nul
if not defined PY (
    echo Chua co venv. Chay: cd /d "%HERE%" ^&^& python -m venv venv ^&^& venv\Scripts\pip install -r requirements.txt
    pause
    exit /b 1
)
"%PY%" "%HERE%menu.py" %*
rem Bam dup tu Explorer -> giu cua so lai de doc ket qua
echo %CMDCMDLINE% | find /i "/c" >nul && pause
exit /b 0
