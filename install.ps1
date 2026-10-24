# Installation et mise à jour du panel AC EVO sous Windows (Docker Desktop).
#
#   Dans « Terminal (administrateur) » :
#   irm https://raw.githubusercontent.com/Zyphro3D/pannel-ac-evo-server/master/install.ps1 | iex
#
# Relancer la même commande met le panel à jour : réglages (.env), base de données, fichiers du jeu
# et configurations sont conservés. Fait tout ce qui était manuel : Docker Desktop (installé par winget
# s'il manque), téléchargement de la dernière release (sans git, signature et empreinte vérifiées), .env
# avec clés et mots de passe générés, fichier override, pare-feu Windows, construction et démarrage.
# Le serveur de jeu se télécharge ensuite depuis le panel (SteamCMD est installé automatiquement).
# Installe aussi l'agent de mise à jour (tâche planifiée à l'ouverture de session) : le bouton
# « Mettre à jour » du panel relance ce script. Une mise à jour qui échoue revient à la version précédente.
#
# Variables facultatives (à définir avant la commande) :
#   $AcePanelDir     dossier d'installation (défaut : <profil>\ace-evo-panel)
#   $AcePanelVersion version à installer, ex. "v2.2.0" (défaut : la dernière release)
#   $AcePanelSource  archive .zip locale au lieu du téléchargement (tests)
# L'agent lance le script avec les variables d'environnement ACE_PANEL_DIR et ACE_PANEL_FROM_PANEL=1.

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$Repo = 'Zyphro3D/pannel-ac-evo-server'
$TaskName = 'AC EVO Panel - mises a jour'
if (-not $AcePanelDir -and $env:ACE_PANEL_DIR) { $AcePanelDir = $env:ACE_PANEL_DIR }
$Dir = if ($AcePanelDir) { $AcePanelDir } else { Join-Path $env:USERPROFILE 'ace-evo-panel' }
$FromPanel = $env:ACE_PANEL_FROM_PANEL -eq '1'
$targetVersion = ''

function Write-Utf8NoBom($path, $text) {
    # docker compose et python-dotenv lisent mal un .env avec BOM (première clé corrompue)
    [IO.File]::WriteAllText($path, $text, (New-Object Text.UTF8Encoding $false))
}

function Set-Status($phase, $message = '') {
    # Avancement lu par la page « Mise à jour du panel » (mode agent seulement) ; écriture puis
    # renommage pour que la page ne lise jamais un fichier à moitié écrit
    if (-not $FromPanel) { return }
    try {
        $msg = ($message -replace '["\\]', '' -replace '\s+', ' ')
        if ($msg.Length -gt 300) { $msg = $msg.Substring(0, 300) }
        $epoch = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
        $tmpStatus = Join-Path $Dir ("update\.status-" + [guid]::NewGuid() + '.tmp')
        Write-Utf8NoBom $tmpStatus ('{"phase": "' + $phase + '", "message": "' + $msg + '", "version": "' + $targetVersion.TrimStart('v') + '", "updated_at": ' + $epoch + "}`n")
        Move-Item -Force $tmpStatus (Join-Path $Dir 'update\status.json')
    } catch { }
}

function Say($m)  { Write-Host "==> $m" -ForegroundColor Cyan }
function Ok($m)   { Write-Host " v  $m" -ForegroundColor Green }
function Warn($m) { Write-Host " !  $m" -ForegroundColor Yellow }
function Die($m)  { Write-Host " x  $m" -ForegroundColor Red; Set-Status 'error' $m; throw $m }

function Get-RandomHex($chars) {
    $bytes = New-Object byte[] ([math]::Ceiling($chars / 2))
    [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    (($bytes | ForEach-Object { $_.ToString('x2') }) -join '').Substring(0, $chars)
}

function Invoke-Native([scriptblock] $Command) {
    # Exécute docker sans que ses messages sur stderr (progression) soient pris pour des erreurs.
    # Bloc de script plutôt que liste d'arguments : PowerShell prendrait « -d » pour un de ses paramètres.
    $prev = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
    try { & $Command 2>&1 | ForEach-Object { "$_" } }
    finally { $ErrorActionPreference = $prev }
}

# Droits d'administration pour l'installation (pare-feu, profil réseau). Pas pour l'agent : un jeton
# élevé lancé par une tâche planifiée a sa propre session de connexion, où le gestionnaire
# d'identifiants Windows est absent et où Docker ne peut plus récupérer les images.
$admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $admin -and -not $FromPanel) { Die 'Lancez cette commande dans « Terminal (administrateur) » (clic droit sur Démarrer).' }

if ($FromPanel) {
    # Une seule mise à jour à la fois, même si deux agents tournent (verrou système nommé)
    $lock = New-Object Threading.Mutex($false, 'Local\AceEvoPanelUpdate')
    if (-not $lock.WaitOne(0)) { Write-Host 'Mise à jour déjà en cours'; return }
    # Demande déposée par le panel : seule une version X.Y.Z est acceptée, et elle est consommée tout
    # de suite (l'agent ne la rejoue pas en boucle si quelque chose échoue)
    $reqFile = Join-Path $Dir 'update\request.json'
    $req = if (Test-Path $reqFile) { [IO.File]::ReadAllText($reqFile) } else { '' }
    Remove-Item -Force $reqFile -ErrorAction SilentlyContinue
    if ($req.Length -gt 4096 -or $req -notmatch '"version":\s*"(\d+\.\d+\.\d+)"') { Die 'Demande de mise à jour illisible' }
    $AcePanelVersion = 'v' + $Matches[1]
    $AcePanelSource = $null
    $targetVersion = $AcePanelVersion
    Write-Host "──── $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') mise à jour vers $AcePanelVersion demandée depuis le panel"
}

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
Ok ("Docker " + (Invoke-Native { docker version --format '{{.Server.Version}}' }))

# ── 2. Récupération et vérification du panel ─────────────────────────────────
Set-Status 'download' "Téléchargement de $targetVersion"
# Image du panel en place : elle contient le vérificateur de signature de la version installée
$panelImg = (Invoke-Native { docker inspect --format '{{.Image}}' ace-panel }) | Where-Object { $_ -match '^sha256:' } | Select-Object -First 1
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
        # ACE_PANEL_RELEASE_BASE (.env) : autre dossier de releases, pour tester une mise à jour avant
        # publication (la signature reste exigée avec la clé du panel installé)
        $envFile = Join-Path $Dir '.env'
        $releaseBase = if ((Test-Path $envFile) -and ([IO.File]::ReadAllText($envFile) -match '(?m)^ACE_PANEL_RELEASE_BASE=(\S+)')) { $Matches[1].TrimEnd('/') } else { '' }
        if ($releaseBase -and $AcePanelVersion) {
            $tag = $AcePanelVersion
            $base = $releaseBase
        } else {
            $api = if ($AcePanelVersion) { "https://api.github.com/repos/$Repo/releases/tags/$AcePanelVersion" } else { "https://api.github.com/repos/$Repo/releases/latest" }
            $tag = (Invoke-RestMethod $api).tag_name
            if (-not $tag) { Die 'Version de la release illisible' }
            $base = "https://github.com/$Repo/releases/download/$tag"
        }
        $targetVersion = $tag
        Say "Téléchargement du panel $tag"
        Invoke-WebRequest -UseBasicParsing "$base/pannel-ac-evo-docker-$tag.zip" -OutFile $zip

        Set-Status 'verify' 'Vérification de la signature'
        $signed = $false
        try {
            Invoke-WebRequest -UseBasicParsing "$base/latest-stable.json" -OutFile (Join-Path $tmp 'latest-stable.json')
            Invoke-WebRequest -UseBasicParsing "$base/latest-stable.json.sig" -OutFile (Join-Path $tmp 'latest-stable.json.sig')
            $haveManifest = $true
        } catch { $haveManifest = $false }
        if ($haveManifest -and $panelImg) {
            $out = Invoke-Native { docker run --rm --entrypoint python -v "${tmp}:/verify:ro" $panelImg /panel/release/verify_release.py /verify/latest-stable.json /verify/latest-stable.json.sig /verify/panel.zip $tag }
            if ($LASTEXITCODE -eq 0) { $signed = $true; Ok 'Signature et empreinte vérifiées' }
            elseif (-not ($out -match 'No such file')) { Die ("Release refusée : " + (($out -join ' ') -replace '^refusé : ', '')) }
        }
        if (-not $signed) {
            # Première installation (aucun code de confiance en place) ou release sans manifeste signé
            if ($FromPanel) { Die "Release $tag sans signature vérifiable : mise à jour refusée" }
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
    }

    $src = Join-Path $tmp 'src'
    Expand-Archive -Force $zip $src
    if (-not (Test-Path (Join-Path $src 'docker-compose.yml'))) { Die 'Archive inattendue (pas de docker-compose.yml)' }

    $firstInstall = -not (Test-Path (Join-Path $Dir '.env'))

    # ── 3. Sauvegarde pour le retour arrière (mise à jour seulement) ─────────
    # Code (hors données de l'utilisateur) et images en place : restaurés si la nouvelle version ne se
    # construit pas ou si le panel ne répond plus. Rangés hors du dossier update/ partagé avec le panel.
    $rollback = $false
    if (-not $firstInstall -and $panelImg) {
        $rb = Join-Path $Dir '.rollback\code'
        Remove-Item -Recurse -Force (Join-Path $Dir '.rollback') -ErrorAction SilentlyContinue
        robocopy $Dir $rb /E /NFL /NDL /NJH /NJS /NP /XD aceserver media update .rollback logs data .git /XF .env update.log | Out-Null
        if ($LASTEXITCODE -ge 8) { Die 'Sauvegarde du code impossible' }
        $panelName = (Invoke-Native { docker inspect --format '{{.Config.Image}}' ace-panel }) | Select-Object -First 1
        $serverImg = (Invoke-Native { docker inspect --format '{{.Image}}' ace-server }) | Where-Object { $_ -match '^sha256:' } | Select-Object -First 1
        $serverName = if ($serverImg) { (Invoke-Native { docker inspect --format '{{.Config.Image}}' ace-server }) | Select-Object -First 1 } else { '' }
        # Un tag garde les images en place : sans lui, une image qui perd son nom à la construction
        # est effacée dès qu'aucun container ne l'utilise (stockage containerd de Docker)
        # (par le nom : avant la construction il désigne l'image en service ; l'identifiant renvoyé
        # par « docker inspect » d'un container n'est pas accepté par « docker tag » avec containerd)
        Invoke-Native { docker tag $panelName ace-evo-panel-rollback:panel } | Out-Null
        if ($serverImg) { Invoke-Native { docker tag $serverName ace-evo-panel-rollback:server } | Out-Null }
        $rollback = $true
    }

    New-Item -ItemType Directory -Force $Dir | Out-Null
    # Les données de l'utilisateur ne sont pas dans l'archive (.env, base, configurations, fichiers du jeu) :
    # la copier par-dessus remplace le code et garde tout le reste.
    Copy-Item -Recurse -Force (Join-Path $src '*') $Dir
    Ok "Panel $tag copié dans $Dir"
} finally {
    Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue
}
Set-Location $Dir

# ── 4. Réglages (première installation seulement) ────────────────────────────
New-Item -ItemType Directory -Force 'aceserver\configs', 'media', 'update' | Out-Null
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

# ── 5. Pare-feu Windows : panel et serveur de jeu joignables depuis le réseau ─
# (installation à la main seulement : l'agent n'a pas les droits, et les règles existent déjà)
if (-not $FromPanel) {
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
}

# ── 6. Construction et démarrage ─────────────────────────────────────────────
# Serveurs de jeu en marche avant la mise à jour : seuls eux sont relancés ensuite (un serveur
# arrêté ne doit pas se retrouver démarré, et inscrit dans la liste publique, par une mise à jour)
$runningBefore = @(Invoke-Native { docker compose ps --services --status running })
$start = @('panel', 'dockerproxy') + @($runningBefore | Where-Object { $_ -and $_ -notin 'panel', 'dockerproxy' })

function Wait-Panel {
    $deadline = (Get-Date).AddMinutes(5)
    while ((Get-Date) -lt $deadline) {
        try { Invoke-WebRequest -UseBasicParsing "http://localhost:$port/login" -TimeoutSec 5 | Out-Null; return $true } catch { Start-Sleep 5 }
    }
    return $false
}

function Undo-Update($reason) {
    Warn "$reason : retour à la version précédente"
    Set-Status 'rollback' $reason
    # Copy-Item écrase toujours (robocopy saute un fichier de même taille et même date, même avec /IS)
    Copy-Item -Recurse -Force (Join-Path $Dir '.rollback\code\*') $Dir
    Invoke-Native { docker tag ace-evo-panel-rollback:panel $panelName } | Out-Null
    if ($serverImg) { Invoke-Native { docker tag ace-evo-panel-rollback:server $serverName } | Out-Null }
    # --force-recreate : seul le contenu de l'image a changé, compose garderait le container cassé
    Invoke-Native { docker compose up -d --no-build --force-recreate @start } | Out-Null
    Wait-Panel | Out-Null
    Set-Status 'rolled_back' $reason
    Write-Host " x  Mise à jour annulée ($reason) : version précédente rétablie" -ForegroundColor Red
    throw "Mise à jour annulée ($reason)"
}

Set-Status 'build' "Construction de $tag"
Say 'Construction et démarrage (premier lancement : environ 10 minutes)'
$env:GIT_HASH = $tag
$out = Invoke-Native { docker compose up --build --no-start --remove-orphans }
if ($LASTEXITCODE -ne 0) {
    $out | Select-Object -Last 10 | ForEach-Object { "    $_" }
    if ($rollback) { Undo-Update 'construction impossible' }
    Die 'La construction a échoué (voir ci-dessus).'
}
Set-Status 'restart' 'Redémarrage du panel'
$out = Invoke-Native { docker compose up -d @start }
$out | Select-Object -Last 5 | ForEach-Object { "    $_" }
if ($LASTEXITCODE -ne 0) { if ($rollback) { Undo-Update 'démarrage impossible' }; Die 'docker compose up a échoué (voir ci-dessus).' }

Say 'Attente du panel'
if (-not (Wait-Panel)) {
    if ($rollback) { Undo-Update 'le panel ne répond pas après la mise à jour' }
    Die "Le panel ne répond pas : docker compose -f `"$Dir\docker-compose.yml`" logs panel"
}

# ── 7. Agent de mise à jour : le bouton du panel relance ce script ───────────
# Tâche planifiée à l'ouverture de session (Docker Desktop ne tourne que dans la session de
# l'utilisateur), avec ses droits normaux : une boucle discrète vérifie toutes les 30 s si le panel
# a déposé une demande et lance alors ce script, dans un processus séparé.
$agent = Join-Path $Dir 'update-agent.ps1'
# install.ps1 est lu explicitement en UTF-8 : Windows PowerShell lirait un fichier sans BOM en ANSI
# (accents des messages affichés par le panel). L'agent lui-même est écrit avec BOM pour la même raison.
$agentText = @"
# Agent de mise à jour du panel AC EVO (écrit par install.ps1) : ne pas modifier.
`$env:ACE_PANEL_DIR = '$Dir'
`$env:ACE_PANEL_FROM_PANEL = '1'
`$run = "& ([scriptblock]::Create([IO.File]::ReadAllText('$Dir\install.ps1', [Text.Encoding]::UTF8)))"
while (`$true) {
    if (Test-Path '$Dir\update\request.json') {
        try {
            Start-Process powershell.exe -Wait -WindowStyle Hidden -RedirectStandardOutput '$Dir\update.log' ``
                -RedirectStandardError '$Dir\update-errors.log' ``
                -ArgumentList "-NoProfile -ExecutionPolicy Bypass -Command ```"`$run```""
        } catch { }
    }
    Start-Sleep 30
}
"@
[IO.File]::WriteAllText($agent, $agentText, (New-Object Text.UTF8Encoding $true))
if (-not $FromPanel) {
    # Pas pendant une mise à jour demandée par le panel : arrêter la tâche tuerait ce script lui-même
    $action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$agent`""
    # Identité réelle (MACHINE\compte) : $env:USERDOMAIN vaut « WORKGROUP » dans certaines sessions
    $me = [Security.Principal.WindowsIdentity]::GetCurrent().Name
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $me
    $principal = New-ScheduledTaskPrincipal -UserId $me -LogonType Interactive -RunLevel Limited
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null
    Start-ScheduledTask -TaskName $TaskName
    $epoch = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
    Write-Utf8NoBom (Join-Path $Dir 'update\agent.json') ('{"agent": "scheduled-task", "installed_at": ' + $epoch + "}`n")
    Ok 'Mise à jour depuis le panel activée (tâche planifiée à l''ouverture de session)'
}

Remove-Item -Recurse -Force (Join-Path $Dir '.rollback') -ErrorAction SilentlyContinue
Invoke-Native { docker rmi ace-evo-panel-rollback:panel ace-evo-panel-rollback:server } | Out-Null
Set-Status 'done' "Panel $tag en ligne"
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

   Étape suivante : connectez-vous en superadmin, le panel propose de télécharger le serveur
   ACE EVO (il suffit de votre compte Steam). Ports à rediriger sur la box vers cette machine
   pour les joueurs : 9700 TCP+UDP et 8081 TCP. Docker Desktop doit rester lancé.
"@
}
