# Contribuer au projet

Merci de l'intérêt porté à AC EVO Server Panel !

**Ce projet n'accepte pas de contributions de code (pull requests).** Le développement est assuré uniquement par le mainteneur. En revanche, les retours suivants sont les bienvenus et lus avec attention :

- 🐛 **Signalements de bug**
- 💡 **Suggestions de fonctionnalités**

## Signaler un bug

Ouvrez une [issue GitHub](https://github.com/Zyphro3D/pannel-ac-evo-server/issues) en indiquant si possible :

- La **version du panel** (visible dans le footer de l'interface, ou dans `VERSION` à la racine du dépôt)
- Ce que vous attendiez vs ce qui s'est passé
- Les logs concernés : `docker compose logs panel --tail 100` (et `docker compose logs ace-server --tail 100` si le souci concerne le serveur de jeu)
- Les étapes pour reproduire, si vous les connaissez

Évitez de coller des secrets (mots de passe, webhooks Discord, tokens) dans une issue publique — masquez-les si besoin.

## Proposer une fonctionnalité

Ouvrez une issue en décrivant :
- Le besoin ou le problème que ça résout
- L'usage envisagé (pour vous, pour un club, pour un événement précis...)

Aucune garantie que la suggestion soit implémentée ni sur quel délai, mais chaque retour aide à prioriser la suite.

## Traductions

Le panel supporte 5 langues (FR / EN / ES / DE / IT). Si vous repérez une traduction manquante ou incorrecte dans l'interface, une issue avec la chaîne concernée et la langue est suffisante — inutile de proposer un patch, la correction se fait côté mainteneur.

## Licence

Ce projet est distribué sous licence [CC BY-NC 4.0](LICENSE) — usage personnel et communautaire libre, usage commercial interdit.
