@echo off
setlocal EnableDelayedExpansion
title AC EVO Panel - Mise a jour

echo.
echo  ================================================
echo   AC EVO Panel - Mise a jour
echo  ================================================
echo.

:: -- Verifications prerequis --------------------------------------------------
if not exist ".venv\Scripts\python.exe" (
    echo [ERREUR] Environnement virtuel introuvable.
    echo Lancez install.bat d'abord.
    pause & exit /b 1
)

:: -- Version actuelle ---------------------------------------------------------
set VERSION_BEFORE=?
if exist "VERSION" set /p VERSION_BEFORE=<VERSION

:: -- Git pull -----------------------------------------------------------------
git --version >nul 2>&1
if errorlevel 1 (
    echo [AVERTISSEMENT] Git non trouve - mise a jour du code ignoree.
    echo Copiez les fichiers manuellement si necessaire.
    goto :install_deps
)

echo  Recuperation des mises a jour...
git pull
if errorlevel 1 (
    echo [ERREUR] Echec du git pull.
    echo Verifiez votre connexion ou les conflits locaux.
    pause & exit /b 1
)

:: -- Version apres ------------------------------------------------------------
set VERSION_AFTER=?
if exist "VERSION" set /p VERSION_AFTER=<VERSION

if "!VERSION_BEFORE!"=="!VERSION_AFTER!" (
    echo  [OK] Deja a jour ^(v!VERSION_AFTER!^).
) else (
    echo  [OK] v!VERSION_BEFORE! -> v!VERSION_AFTER!
)

:install_deps
:: -- Mise a jour des dependances ----------------------------------------------
echo.
echo  Mise a jour des dependances Python...
.venv\Scripts\pip install -r requirements.txt --quiet --upgrade
if errorlevel 1 (
    echo [ERREUR] Echec pip install.
    pause & exit /b 1
)
echo  [OK] Dependances a jour.

:: -- Recompiler les traductions -----------------------------------------------
if exist "compile_mo.py" (
    echo  Compilation des traductions...
    .venv\Scripts\python compile_mo.py >nul 2>&1
    echo  [OK] Traductions compilees.
)

:: -- Rappel : .env et DB jamais touches ---------------------------------------
echo.
echo  [INFO] Votre .env et votre base de donnees sont intacts.

echo.
echo  ================================================
echo   Mise a jour terminee
echo   Relancez start.bat pour appliquer les changements
echo  ================================================
echo.
pause
