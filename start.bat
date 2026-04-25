@echo off
setlocal EnableDelayedExpansion
title AC EVO Panel

:: -- Verifications -----------------------------------------------------------
if not exist ".venv\Scripts\python.exe" (
    echo [ERREUR] L'environnement virtuel est manquant.
    echo Lancez install.bat d'abord.
    pause & exit /b 1
)
if not exist ".env" (
    echo [ERREUR] Le fichier .env est manquant.
    echo Lancez install.bat d'abord.
    pause & exit /b 1
)

:: -- Lire le port depuis .env (defaut 4300) ----------------------------------
set PORT=4300
for /f "usebackq tokens=1,* delims==" %%a in (".env") do (
    if "%%a"=="PANEL_PORT" set PORT=%%b
)

:: -- Lire la version ---------------------------------------------------------
set VERSION=?
if exist "VERSION" set /p VERSION=<VERSION

:: -- Demarrer ----------------------------------------------------------------
echo.
echo  ================================================
echo   AC EVO Panel  v!VERSION!
echo  ================================================
echo.
echo   Demarrage sur http://localhost:!PORT!
echo   Appuyez sur Ctrl+C pour arreter.
echo.

.venv\Scripts\python run.py
