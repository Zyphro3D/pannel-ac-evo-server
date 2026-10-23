# Installation et mise à jour du panel AC EVO sous Windows (Docker Desktop).
#
#   Dans « Terminal (administrateur) » :
#   irm https://raw.githubusercontent.com/Zyphro3D/pannel-ac-evo-server/master/install.ps1 | iex
#
# Relancer la même commande met le panel à jour : réglages (.env), base de données, fichiers du jeu
# et configurations sont conservés. Fait tout ce qui était manuel : Docker Desktop (installé par winget
# s'il manque), téléchargement de la dernière release (sans git, empreinte SHA-256 vérifiée), .env avec
# clés et mots de passe générés, fichier override, pare-feu Windows, construction et démarrage.
# Le serveur de jeu se télécharge ensuite depuis le panel (SteamCMD est installé automatiquement).
#
# Variables facultatives (à définir avant la commande) :
#   $AcePanelDir     dossier d'installation (défaut : <profil>\ace-evo-panel)
#   $AcePanelVersion version à installer, ex. "v2.2.0" (défaut : la dernière release)
#   $AcePanelSource  archive .zip locale au lieu du téléchargement (tests)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$Repo = 'Zyphro3D/pannel-ac-evo-server'
$Dir = if ($AcePanelDir) { $AcePanelDir } else { Join-Path $env:USERPROFILE 'ace-evo-panel' }

function Say($m)  { Write-Host "==> $m" -ForegroundColor Cyan }
function Ok($m)   { Write-Host " v  $m" -ForegroundColor Green }
function Warn($m) { Write-Host " !  $m" -ForegroundColor Yellow }
function Die($m)  { Write-Host " x  $m" -ForegroundColor Red; throw $m }

function Write-Utf8NoBom($path, $text) {
    # docker compose et python-dotenv lisent mal un .env avec BOM (première clé corrompue)
    [IO.File]::WriteAllText($path, $text, (New-Object Text.UTF8Encoding $false))
}

function Get-RandomHex($chars) {
    $bytes = New-Object byte[] ([math]::Ceiling($chars / 2))
    [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    (($bytes | ForEach-Object { $_.ToString('x2') }) -join '').Substring(0, $chars)
}

function Invoke-Native {
    # Exécute docker sans que ses messages sur stderr (progression) soient pris pour des erreurs
    param([Parameter(ValueFromRemainingArguments)] $Cmd)
    $prev = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
    try { & $Cmd[0] $Cmd[1..($Cmd.Count - 1)] 2>&1 | ForEach-Object { "$_" } }
    finally { $ErrorActionPreference = $prev }
}

$admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $admin) { Die 'Lancez cette commande dans « Terminal (administrateur) » (clic droit sur Démarrer).' }

# ── 1. Docker Desktop ────────────────────────────────────────────────────────
$dockerBin = 'C:\Program Files\Docker\Docker\resources\bin'
$dockerApp = 'C:\Program Files\Docker\Docker\Docker Desktop.exe'
if (-not (Test-Path $dockerApp)) {
    Say 'Docker Desktop absent : installation (winget)'
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) { Die 'winget introuvable : installez Docker Desktop (https://www.docker.com/products/docker-desktop/) puis relancez.' }
    winget install --id Docker.DockerDesktop -e --accept-package-agreements --accept-source-agreements
    if (-not (Test-Path $dockerApp)) { Die "L'installation de Docker Desktop a échoué." }
    Warn 'Docker Desktop est installé. Redémarrez Windows, ouvrez Docker Desktop une fois (accepter les conditions), puis relancez cette commande.'
    return
}
if ($env:Path -notlike "*$dockerBin*") { $env:Path = "$env:Path;$dockerBin" }

function Test-Engine { $prev = $ErrorActionPreference; $ErrorActionPreference = 'Continue'; docker info *> $null; $r = $?; $ErrorActionPreference = $prev; $r }
if (-not (Test-Engine)) {
    Say 'Démarrage de Docker Desktop'
    Start-Process $dockerApp
    $t = 0
    while (-not (Test-Engine) -and $t -lt 240) { Start-Sleep 5; $t += 5 }
    if (-not (Test-Engine)) { Die "Docker Desktop ne répond pas. Ouvrez-le, attendez « Engine running », puis relancez." }
}
Ok ("Docker " + (Invoke-Native docker version --format '{{.Server.Version}}'))

# ── 2. Récupération du panel ─────────────────────────────────────────────────
$tmp = Join-Path ([IO.Path]::GetTempPath()) ("ace-panel-" + [guid]::NewGuid())
New-Item -ItemType Directory -Force $tmp | Out-Null
try {
    $zip = Join-Path $tmp 'panel.zip'
    if ($AcePanelSource) {
        if (-not (Test-Path $AcePanelSource)) { Die "Archive introuvable : $AcePanelSource" }
        Copy-Item $AcePanelSource $zip
        $tag = 'local'
        Ok "Archive locale : $AcePanelSource"
    } else {
        $api = if ($AcePanelVersion) { "https://api.github.com/repos/$Repo/releases/tags/$AcePanelVersion" } else { "https://api.github.com/repos/$Repo/releases/latest" }
        $tag = (Invoke-RestMethod $api).tag_name
        if (-not $tag) { Die 'Version de la release illisible' }
        $base = "https://github.com/$Repo/releases/download/$tag"
        Say "Téléchargement du panel $tag"
        Invoke-WebRequest -UseBasicParsing "$base/pannel-ac-evo-docker-$tag.zip" -OutFile $zip
        try {
            $sums = (Invoke-WebRequest -UseBasicParsing "$base/SHA256SUMS").Content
            if ($sums -is [byte[]]) { $sums = [Text.Encoding]::UTF8.GetString($sums) }
            $line = ($sums -split "`n") | Where-Object { $_ -match " pannel-ac-evo-docker-$([regex]::Escape($tag)).zip\s*$" } | Select-Object -First 1
            $expected = if ($line) { ($line -split ' ')[0].Trim() } else { '' }
            $actual = (Get-FileHash $zip -Algorithm SHA256).Hash.ToLower()
            if (-not $expected -or $expected -ne $actual) { Die 'Empreinte SHA-256 incorrecte : archive refusée' }
            Ok 'Empreinte SHA-256 vérifiée'
        } catch [Net.WebException] {
            Warn "Pas de fichier SHA256SUMS pour $tag (release ancienne) : empreinte non vérifiée"
        }
    }

    $src = Join-Path $tmp 'src'
    Expand-Archive -Force $zip $src
    if (-not (Test-Path (Join-Path $src 'docker-compose.yml'))) { Die 'Archive inattendue (pas de docker-compose.yml)' }

    $firstInstall = -not (Test-Path (Join-Path $Dir '.env'))
    New-Item -ItemType Directory -Force $Dir | Out-Null
    # Les données de l'utilisateur ne sont pas dans l'archive (.env, base, configurations, fichiers du jeu) :
    # la copier par-dessus remplace le code et garde tout le reste.
    Copy-Item -Recurse -Force (Join-Path $src '*') $Dir
    Ok "Panel $tag copié dans $Dir"
} finally {
    Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue
}
Set-Location $Dir

# ── 3. Réglages (première installation seulement) ────────────────────────────
New-Item -ItemType Directory -Force 'aceserver\configs', 'media' | Out-Null
# Ce fichier doit exister avant le démarrage (sinon Docker crée un dossier à sa place)
if ((Test-Path 'docker-compose.override.yml' -PathType Container)) { Remove-Item 'docker-compose.override.yml' }
if (-not (Test-Path 'docker-compose.override.yml')) { Write-Utf8NoBom (Join-Path $Dir 'docker-compose.override.yml') '' }

$envText = if (Test-Path '.env') { [IO.File]::ReadAllText((Join-Path $Dir '.env')) } else { '' }
$port = if ($envText -match '(?m)^PANEL_PORT=(\d+)') { $Matches[1] } else { '4300' }
$ip = (Get-NetIPConfiguration | Where-Object { $_.IPv4DefaultGateway } | Select-Object -First 1).IPv4Address.IPAddress
if (-not $ip) { $ip = 'localhost' }

if ($firstInstall) {
    $adminPw = Get-RandomHex 16
    $superPw = Get-RandomHex 20
    $values = @{
        SECRET_KEY            = Get-RandomHex 64
        ADMIN_PASSWORD        = $adminPw
        SUPERADMIN_PASSWORD   = $superPw
        RESULTS_INGEST_SECRET = Get-RandomHex 32
        PANEL_URL             = "http://${ip}:$port"
        SESSION_COOKIE_SECURE = 'false'
    }
    $lines = [IO.File]::ReadAllLines((Join-Path $Dir '.env.example')) | ForEach-Object {
        $k = ($_ -split '=', 2)[0]
        if ($_ -notmatch '^\s*#' -and $values.ContainsKey($k)) { "$k=$($values[$k])" } else { $_ }
    }
    Write-Utf8NoBom (Join-Path $Dir '.env') (($lines -join "`n") + "`n")
    Ok 'Réglages créés (.env) : clés et mots de passe générés'
} else {
    Ok 'Réglages existants conservés (.env)'
}

# ── 4. Pare-feu Windows : panel et serveur de jeu joignables depuis le réseau ─
$netProfile = Get-NetConnectionProfile | Where-Object { $_.IPv4Connectivity -ne 'Disconnected' } | Select-Object -First 1
if ($netProfile -and $netProfile.NetworkCategory -eq 'Public') {
    Warn "Le réseau « $($netProfile.Name) » est classé Public : Windows y bloque le panel et le serveur de jeu."
    $answer = Read-Host 'Le classer en réseau Privé (réseau de confiance, ex. à la maison) ? [O/n]'
    if ($answer -eq '' -or $answer -match '^(o|oui|y|yes)$') {
        Set-NetConnectionProfile -InterfaceIndex $netProfile.InterfaceIndex -NetworkCategory Private
        Ok 'Réseau classé Privé'
    } else {
        Warn 'Réseau laissé en Public : le panel ne sera joignable que depuis cette machine.'
    }
}
Get-NetFirewallRule -Name 'ace-evo-panel-*' -ErrorAction SilentlyContinue | Remove-NetFirewallRule
New-NetFirewallRule -Name 'ace-evo-panel-tcp' -DisplayName 'AC EVO Panel (TCP)' -Direction Inbound -Protocol TCP `
    -LocalPort $port, 9700, 8081 -Action Allow -Profile Private, Domain | Out-Null
New-NetFirewallRule -Name 'ace-evo-panel-udp' -DisplayName 'AC EVO Panel (UDP)' -Direction Inbound -Protocol UDP `
    -LocalPort 9700 -Action Allow -Profile Private, Domain | Out-Null
Ok "Pare-feu : TCP $port, 9700, 8081 et UDP 9700 ouverts (réseaux privés)"

# ── 5. Construction et démarrage ─────────────────────────────────────────────
Say 'Construction et démarrage (premier lancement : environ 10 minutes)'
$env:GIT_HASH = $tag
$out = Invoke-Native docker compose up -d --build --remove-orphans
$out | Select-Object -Last 5 | ForEach-Object { "    $_" }
if ($LASTEXITCODE -ne 0) { Die 'docker compose up a échoué (voir ci-dessus).' }

Say 'Attente du panel'
$up = $false
for ($i = 0; $i -lt 60 -and -not $up; $i++) {
    try { Invoke-WebRequest -UseBasicParsing "http://localhost:$port/login" -TimeoutSec 5 | Out-Null; $up = $true } catch { Start-Sleep 5 }
}
if (-not $up) { Die "Le panel ne répond pas : docker compose -f `"$Dir\docker-compose.yml`" logs panel" }

Write-Host ''
Ok "Panel AC EVO $tag en ligne : http://${ip}:$port"
if ($firstInstall) {
    $envNow = [IO.File]::ReadAllText((Join-Path $Dir '.env'))
    $superUser = if ($envNow -match '(?m)^SUPERADMIN_USERNAME=(.*)$') { $Matches[1].Trim() } else { 'superadmin' }
    $adminUser = if ($envNow -match '(?m)^ADMIN_USERNAME=(.*)$') { $Matches[1].Trim() } else { 'admin' }
    Write-Host @"

   Identifiants (à changer dans le panel, également dans $Dir\.env) :
     superadmin : $superUser / $superPw
     admin      : $adminUser / $adminPw

   Étape suivante : connectez-vous en superadmin, puis Paramètres → mise à jour du serveur
   (SteamCMD) pour télécharger le serveur ACE EVO. Ports à rediriger sur la box vers cette
   machine pour les joueurs : 9700 TCP+UDP et 8081 TCP. Docker Desktop doit rester lancé.
"@
}
