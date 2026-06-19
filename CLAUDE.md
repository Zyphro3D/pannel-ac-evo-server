@.claude/commands/ui-expert.md
@.claude/commands/backend-expert.md
@.claude/commands/cybersecurity-expert.md
@.claude/commands/code-quality-expert.md
@.claude/commands/performance-expert.md
@.claude/commands/devops-expert.md

# Contexte du projet

**pannel-ac-evo-server** — Panel web Flask pour serveurs Assetto Corsa EVO.
Open source public GitHub, distribution gratuite communautaire.
Développé à 80% pour les autres utilisateurs (clubs, organisateurs de courses).
2 beta testeurs actifs qui pullent les mises à jour rapidement dès qu'elles sont pushées.

> Chaque modification est une release publique quasi-immédiate. Réfléchir avant tout push.

---

# Règles absolues — toujours appliquées

## 1. Internationalisation (i18n)

Tout texte visible par l'utilisateur est une clé de traduction. Sans exception.

- Templates / routes : `_('texte')` pour les strings à la requête
- Niveau module : `_l('texte')` pour les lazy strings (ex: `_ENV_DESCS`)
- 5 langues à maintenir : `fr`, `en`, `de`, `es`, `it` — fichiers dans `translations/{lang}/LC_MESSAGES/messages.po`
- Après toute modification : recompiler avec `docker compose exec panel python compile_mo.py`

## 2. UI — propre, claire, aérée

- Les layouts doivent respirer. Jamais de champs "trop tassés".
- Utiliser en priorité les classes CSS existantes (`main.css`) : `settings-card`, `settings-dashboard-grid`, `btn`, `form-control`, variables CSS `--accent`, `--dim`, `--text`, `--surface2`.
- Hiérarchie visuelle : titre (`h2`) → label (`strong`) → description (`var(--dim)`) → input.
- L'utilisateur type est un organisateur de course non-développeur : l'UX est un critère de qualité.
- Tester visuellement après chaque changement (restart panel + vérification navigateur).

## 3. Sécurité

- **Auth** : toutes les routes admin ont `@login_required` + `@admin_required` (ou `@superadmin_required`). Les nouvelles routes API POST aussi.
- **CSRF** : chaque formulaire POST a `<input type="hidden" name="csrf_token" value="{{ csrf_token() }}">`. Les fetch JS envoient le token en header.
- **Injection** : ORM SQLAlchemy uniquement, jamais de SQL brut avec des variables utilisateur. Jamais d'input utilisateur dans un shell ou commande Docker.
- **XSS** : ne pas utiliser `| safe` sans validation stricte. L'auto-escape Jinja2 est actif.
- **Secrets** : toute clé sensible (webhook, password, token) est dans `_SENSITIVE`, affichée en `type="password"`, jamais loggée.

## 4. Backend — cohérence architecture

- **Thread safety** : `_lb_lock` dans `ace_tcp_client.py` pour tout accès aux dicts partagés.
- **Nouvelle config** : ajouter dans `_ENV_SECTIONS` + `_ENV_DESCS` + `config.py` + `.env.example` + `_SENSITIVE` si sensible.
- **Migration DB** : toute modification de schéma = fonction `_migrate_*` dans `admin.py`, appelée dans `create_app()`.
- **Discord notifier** : `safe_notify(fn, *args)` depuis les threads. `_tmpl(env_key, default, **kwargs)` pour les messages configurables. Lire `os.environ.get()` à l'appel (pas à l'init).
- **Rétrocompatibilité** : les changements doivent fonctionner avec les DB existantes des utilisateurs.

---

# Stack technique

- **Backend** : Python 3.11, Flask, SQLAlchemy, Flask-Babel, Flask-Login
- **Frontend** : Jinja2, CSS vanilla (`main.css`), JS vanilla
- **Deploy** : Docker split — `ace-panel` (port 4300) + `ace-server` (Wine + ACE EVO exe, port 9700 TCP)
- **i18n** : Flask-Babel, compilation via `docker compose exec panel python compile_mo.py`
