@echo off
setlocal EnableDelayedExpansion
title AC EVO Panel - Installation

echo.
echo  ================================================
echo   AC EVO Panel - Installation
echo  ================================================
echo.

:: -- Verifier Python ---------------------------------------------------------
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERREUR] Python n'est pas installe ou pas dans le PATH.
    echo Telecharger Python 3.11+ sur https://python.org
    pause & exit /b 1
)
for /f "tokens=2 delims= " %%v in ('python --version 2^>^&1') do set PYVER=%%v
echo  [OK] Python %PYVER% detecte.

:: -- Creer le venv -----------------------------------------------------------
if not exist ".venv\Scripts\python.exe" (
    echo  Creation de l'environnement virtuel...
    python -m venv .venv
    if errorlevel 1 ( echo [ERREUR] Impossible de creer le venv. & pause & exit /b 1 )
    echo  [OK] Environnement virtuel cree.
) else (
    echo  [OK] Environnement virtuel existant.
)

:: -- Installer les dependances -----------------------------------------------
echo  Installation des dependances...
.venv\Scripts\pip install -r requirements.txt --quiet
if errorlevel 1 ( echo [ERREUR] Echec pip install. & pause & exit /b 1 )
echo  [OK] Dependances installees.

:: -- Creer le .env si absent -------------------------------------------------
if exist ".env" (
    echo  [OK] Fichier .env existant - configuration conservee.
    goto :compile_mo
)

echo.
echo  ------------------------------------------------
echo   Configuration initiale
echo  ------------------------------------------------
echo.

:: Generer une SECRET_KEY
for /f %%k in ('.venv\Scripts\python -c "import secrets; print(secrets.token_hex(32))"') do set SECRET_KEY=%%k

:: Dossier serveur ACE
echo  Chemin du dossier d'installation ACE EVO Server
echo  (ex: C:\aceserver)
set /p ACESERVER_DIR="  > "
if "!ACESERVER_DIR!"=="" set ACESERVER_DIR=C:\aceserver

:: Dossier configs
echo.
echo  Chemin du dossier de configurations du panel
echo  (ex: C:\Users\%USERNAME%\Documents\ACE)
set /p CONFIGS_DIR="  > "
if "!CONFIGS_DIR!"=="" set CONFIGS_DIR=C:\Users\%USERNAME%\Documents\ACE

:: Mots de passe admin
echo.
echo  Mot de passe compte ADMIN (acces standard)
set /p ADMIN_PASSWORD="  > "
if "!ADMIN_PASSWORD!"=="" set ADMIN_PASSWORD=admin

echo.
echo  Mot de passe compte SUPERADMIN (acces complet)
set /p SUPERADMIN_PASSWORD="  > "
if "!SUPERADMIN_PASSWORD!"=="" set SUPERADMIN_PASSWORD=superadmin

:: URL publique
echo.
echo  URL publique du panel (ex: https://evo.monsite.fr ou http://localhost:4300)
set /p PANEL_URL="  > "
if "!PANEL_URL!"=="" set PANEL_URL=http://localhost:4300

:: HTTP local ou HTTPS
set COOKIE_SECURE=true
echo  !PANEL_URL! | findstr /i "https" >nul
if errorlevel 1 set COOKIE_SECURE=false

:: Ecrire le .env
(
echo SECRET_KEY=!SECRET_KEY!
echo.
echo ADMIN_USERNAME=admin
echo ADMIN_PASSWORD=!ADMIN_PASSWORD!
echo SUPERADMIN_USERNAME=superadmin
echo SUPERADMIN_PASSWORD=!SUPERADMIN_PASSWORD!
echo.
echo ACESERVER_DIR=!ACESERVER_DIR!
echo CONFIGS_DIR=!CONFIGS_DIR!
echo.
echo ACESERVER_HTTP_PORT=8080
echo SERVER_SHOW_CONSOLE=false
echo.
echo DATABASE_URL=sqlite:///ace_evo.db
echo.
echo MAIL_SERVER=
echo MAIL_PORT=587
echo MAIL_USE_TLS=true
echo MAIL_USERNAME=
echo MAIL_PASSWORD=
echo MAIL_FROM=
echo MAIL_ADMIN=
echo.
echo PANEL_URL=!PANEL_URL!
echo DISCORD_WEBHOOK_URL=
echo SESSION_COOKIE_SECURE=!COOKIE_SECURE!
) > .env

echo  [OK] Fichier .env cree.

:compile_mo
:: -- Compiler les traductions ------------------------------------------------
if exist "compile_mo.py" (
    .venv\Scripts\python compile_mo.py >nul 2>&1
    echo  [OK] Traductions compilees.
)

:: -- Creer le dossier logs ---------------------------------------------------
if not exist "logs" mkdir logs

echo.
echo  ================================================
echo   Installation terminee avec succes
echo   Lancez start.bat pour demarrer
echo  ================================================
echo.
pause
