@echo off
setlocal EnableDelayedExpansion
title AC EVO Panel - Mise a jour

echo.
echo  ================================================
echo   AC EVO Panel - Mise a jour
echo  ================================================
echo.

:: -- Version actuelle --------------------------------------------------------
set VER_BEFORE=?
if exist "VERSION" set /p VER_BEFORE=<VERSION

:: -- Verifier git ------------------------------------------------------------
git --version >nul 2>&1
if errorlevel 1 (
    echo [ERREUR] Git n'est pas installe ou pas dans le PATH.
    pause & exit /b 1
)

:: -- Sauvegarder .env --------------------------------------------------------
echo  Sauvegarde du fichier .env...
if exist ".env" copy .env .env.backup >nul

:: -- Pull --------------------------------------------------------------------
echo  Telechargement de la mise a jour...
git pull
if errorlevel 1 (
    echo.
    echo [ERREUR] git pull a echoue.
    echo Verifiez votre connexion et que vous n'avez pas de modifications locales.
    if exist ".env.backup" copy .env.backup .env >nul
    pause & exit /b 1
)

:: -- Restaurer .env ----------------------------------------------------------
if exist ".env.backup" (
    copy .env.backup .env >nul
    del .env.backup >nul
)

:: -- Mettre a jour les dependances -------------------------------------------
echo  Mise a jour des dependances...
if exist ".venv\Scripts\pip.exe" (
    .venv\Scripts\pip install -r requirements.txt --quiet
) else (
    echo [ATTENTION] Environnement virtuel absent - lancez install.bat
)

:: -- Recompiler les traductions ----------------------------------------------
if exist "compile_mo.py" (
    .venv\Scripts\python compile_mo.py >nul 2>&1
    echo  [OK] Traductions recompilees.
)

:: -- Resultat ----------------------------------------------------------------
set VER_AFTER=?
if exist "VERSION" set /p VER_AFTER=<VERSION

echo.
echo  ================================================
echo   Mise a jour terminee
if "!VER_BEFORE!"=="!VER_AFTER!" (
echo   Version : !VER_AFTER! (deja a jour)
) else (
echo   !VER_BEFORE! -^> !VER_AFTER!
)
echo  ================================================
echo.
pause
