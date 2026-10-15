@echo off
rem Cai dat 1 lan cho may moi. Thu muc nay phai nam trong ban SAM2:  sam2\cvat_2d
rem   git clone https://github.com/facebookresearch/sam2.git
rem   cd sam2
rem   git clone https://github.com/letuan2k2/cvat-2d-qc.git cvat_2d
rem   cvat_2d\cai_dat.bat
setlocal
set "HERE=%~dp0"
set "ROOT=%~dp0.."
if not exist "%ROOT%\sam2\build_sam.py" (
    echo [LOI] Khong thay thu vien SAM2 o thu muc cha.
    echo Repo nay phai nam trong ban SAM2, dang:  sam2\cvat_2d
    echo   git clone https://github.com/facebookresearch/sam2.git
    echo   cd sam2
    echo   git clone https://github.com/letuan2k2/cvat-2d-qc.git cvat_2d
    exit /b 1
)
where python >nul 2>nul || (
    echo [LOI] Chua cai Python. Cai Python 3.11-3.13 tu python.org, tick "Add python.exe to PATH".
    exit /b 1
)
set "PY=%ROOT%\venv\Scripts\python.exe"
if not exist "%PY%" (
    echo == Tao moi truong venv
    python -m venv "%ROOT%\venv" || exit /b 1
)
"%PY%" -m pip install -U pip
where nvidia-smi >nul 2>nul && (
    echo == Co GPU NVIDIA: cai torch ban CUDA
    "%PY%" -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cu126 || exit /b 1
) || echo == Khong thay GPU NVIDIA: dung torch ban CPU ^(chay rat cham^)
echo == Cai thu vien
"%PY%" -m pip install -r "%HERE%requirements.txt" || exit /b 1
echo == Tai model ^(lan dau khoang 3 GB, can Internet^)
set PYTHONIOENCODING=utf-8
"%PY%" "%HERE%tai_model.py" || exit /b 1
if not exist "%HERE%.env" copy "%HERE%.env.example" "%HERE%.env" >nul
echo.
echo Xong. Chay web_qc.bat roi mo http://localhost:8000
echo Mat khau admin lan dau nam trong web_qc\data\MAT_KHAU_ADMIN.txt
exit /b 0
