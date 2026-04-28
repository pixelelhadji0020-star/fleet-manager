@echo off
cd /d "%~dp0"
title Fleet Manager

echo.
echo ============================================
echo    FLEET MANAGER - Demarrage
echo ============================================
echo.

if not exist "app.py" (
    echo ERREUR : app.py introuvable ici.
    pause
    exit /b 1
)

:: Trouver le bon Python (pas celui de MSYS)
set PYTHON=
for %%P in (
    "%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python310\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python39\python.exe"
    "C:\Python313\python.exe"
    "C:\Python312\python.exe"
    "C:\Python311\python.exe"
    "C:\Python310\python.exe"
) do (
    if exist %%P (
        if not defined PYTHON (
            set PYTHON=%%~P
        )
    )
)

:: Si pas trouvé via chemin fixe, essayer py launcher
if not defined PYTHON (
    py -3 --version >nul 2>&1
    if not errorlevel 1 (
        set PYTHON=py -3
    )
)

if not defined PYTHON (
    echo ERREUR : Python introuvable.
    echo Installez Python depuis https://www.python.org/downloads/
    echo Cochez "Add Python to PATH" lors de l'installation.
    pause
    exit /b 1
)

echo OK - Python trouve : %PYTHON%
echo.

:: Installer pip si manquant puis Flask
echo Installation de Flask...
%PYTHON% -m ensurepip --upgrade >nul 2>&1
%PYTHON% -m pip install flask werkzeug --quiet --no-warn-script-location
if errorlevel 1 (
    echo Tentative alternative...
    %PYTHON% -m pip install flask werkzeug
)

:: Verifier que Flask est bien la
%PYTHON% -c "import flask" >nul 2>&1
if errorlevel 1 (
    echo ERREUR : Flask toujours absent. Voir message ci-dessus.
    pause
    exit /b 1
)

echo OK - Flask installe
echo.
echo ============================================
echo  Navigateur : http://localhost:5000
echo  Admin      : admin@fleet.com
echo  Mot passe  : admin123
echo  Gardez cette fenetre ouverte !
echo ============================================
echo.

start "" cmd /c "timeout /t 3 /nobreak >nul & start http://localhost:5000"

%PYTHON% app.py

pause
