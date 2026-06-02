---
title: Référence CLI
description: Référence complète de l'outil en ligne de commande hsync — tous les drapeaux, sous-commandes et le DSL de requête avancé.
---

# Référence CLI — `hsync`

`hsync` est la **CLI sans interface graphique** de HistorySync. Elle offre toute la puissance de l'application sans GUI, ce qui la rend idéale pour les tâches planifiées, les scripts et les environnements CI.

---

## Options Globales

Ces options sont disponibles sur chaque commande et sous-commande.

| Drapeau | Abrégé | Description |
|---|---|---|
| `--version` | | Afficher la version et quitter |
| `--config-dir PATH` | | Utiliser un répertoire de configuration/données personnalisé |
| `--portable` | | Stocker toutes les données à côté du binaire `hsync` |
| `--verbose` | `-v` | Activer la journalisation au niveau débogage |
| `--quiet` | `-q` | Supprimer la sortie de progression ; imprimer uniquement les erreurs sur stderr |
| `--no-color` | | Désactiver les couleurs ANSI (aussi via la variable d'environnement `NO_COLOR`) |
| `--dry-run` | | Découvrir/valider sans rien écrire |

---

## Drapeaux d'Action Classiques

Actions ponctuelles rapides via des drapeaux (aucune sous-commande requise).

### `-s` / `--sync` — Extraire l'Historique de Navigation

Importer l'historique de navigation dans la base de données locale.

```bash
hsync -s
hsync --sync

# Synchroniser uniquement des navigateurs spécifiques
hsync -s --browsers chrome,firefox

# Synchroniser toutes les 30 minutes (mode veille)
hsync -s -w 30
```

**Options de synchronisation :**

| Drapeau | Description |
|---|---|
| `--browsers LIST` | Types de navigateurs séparés par des virgules (par défaut : tous détectés). Ex. : `chrome,firefox,edge` |
| `-w MINUTES` / `--watch MINUTES` | Répéter la synchronisation toutes les `MINUTES` minutes. Appuyez sur <kbd>Ctrl</kbd>+<kbd>C</kbd> pour arrêter. |

### `-b` / `--backup` — Sauvegarde WebDAV

Téléverser un instantané compressé de la base de données locale vers WebDAV.

```bash
hsync -b
hsync --backup

# Synchroniser puis sauvegarder en une seule opération
hsync -sb
```

!!! note "WebDAV doit être configuré au préalable"
    Exécutez `hsync config set webdav.enabled true` et définissez l'URL, le nom d'utilisateur et le mot de passe avant d'utiliser `--backup`.

<a id="export"></a>

### `-e FICHIER` / `--export FICHIER` — Exporter l'Historique

Exporter l'historique de navigation vers un fichier. Le format est déduit de l'extension du fichier.

```bash
# Exportation de base en CSV
hsync -e history.csv

# Exportation en JSON avec filtres
hsync -e history.json --keyword python --after 2024-01-01

# Rapport HTML avec favicons intégrés
hsync -e report.html --format html --embed-icons

# Filtrer par domaine(s)
hsync -e out.csv --domain github.com --domain stackoverflow.com

# Colonnes personnalisées
hsync -e out.csv --columns title,url,visit_time,browser_type

# Filtre de mots-clés par expression régulière
hsync -e out.json --keyword "^https://github" --regex

# Plage de dates
hsync -e out.csv --after 2024-01-01 --before 2024-12-31
```

**Options d'exportation :**

| Drapeau | Description |
|---|---|
| `--format FMT` | `csv` \| `json` \| `html` (par défaut : déduit de l'extension) |
| `--columns COLS` | Colonnes séparées par des virgules. Disponibles : `id`, `title`, `url`, `visit_time`, `visit_count`, `browser_type`, `profile_name`, `domain`, `metadata`, `typed_count`, `first_visit_time`, `transition_type`, `visit_duration` |
| `--embed-icons` | Intégrer les favicons en URI de données Base64 (exportation HTML uniquement) |
| `--keyword TEXT` | Filtre de mots-clés en texte intégral |
| `--regex` | Traiter `--keyword` comme une expression régulière Python |
| `--browser TYPE` | Filtrer par type de navigateur (ex. : `chrome`, `firefox`, `edge`) |
| `--after DATE` | Inclure les enregistrements à partir du `AAAA-MM-JJ` (inclus) |
| `--before DATE` | Inclure les enregistrements jusqu'au `AAAA-MM-JJ` (inclus) |
| `--domain HOST` | Filtrer par domaine. Répétable : `--domain a.com --domain b.com` |

### `-S` / `--status` — Statistiques de la Base de Données

Afficher les statistiques de la base de données.

```bash
hsync -S
hsync --status

# JSON lisible par machine
hsync -S --json

# Ligne unique condensée (pour les scripts)
hsync -S -q
```

**Exemple de sortie :**
```
Database Status
──────────────────────────────────────────────
     Path          :  /home/user/.config/HistorySync/history.db
     Size          :  124.3 MB
     Records       :  1,482,037
     Domains       :  8,421
     FTS index     :  31.2 MB
     Browsers      :  chrome, firefox, edge, brave
     Last sync     :  2026-05-09 14:32:07
     Last backup   :  2026-05-09 12:00:00
```

### `-i` / `--interactive` — Menu Guidé

Lancer un menu de terminal interactif — idéal pour la première utilisation.

```bash
hsync -i
hsync --interactive
```

---

## Sous-commandes

### `search` — Rechercher dans l'Historique

Rechercher des enregistrements d'historique avec une syntaxe de requête structurée.

```bash
# Parcourir les 20 enregistrements récents
hsync search

# Parcourir les 100 derniers
hsync search --limit 100

# Recherche par mot-clé simple
hsync search python

# Mode interactif avec navigation au clavier
hsync search -i

# Requêtes structurées
hsync search "domain:github.com python"
hsync search "after:2024-01-01 browser:chrome" --limit 50
hsync search "is:bookmarked tag:work" --format json
hsync search "react -tutorial" --open
```

**Options :**

| Drapeau | Défaut | Description |
|---|---|---|
| `--limit N` | `20` | Nombre maximum de résultats |
| `--format FMT` | `table` | Format de sortie : `table` \| `json` \| `tsv` \| `csv` |
| `--columns COLS` | `title,url,visit_time,browser_type` | Colonnes à afficher |
| `--open` | | Ouvrir l'URL du premier résultat dans le navigateur par défaut |
| `-i` / `--interactive` | | Mode de navigation interactif au clavier |

---

<a id="query-dsl"></a>

### DSL de Requête

La sous-commande de recherche et la barre de recherche de l'interface graphique prennent en charge un langage de requête riche.

#### Recherche par Mot-clé

Les mots simples recherchent dans les titres et les URLs :
```
python async
"phrase exacte"
react -tutorial         # exclure un terme
```

#### Filtres par Jeton

| Jeton | Exemple | Description |
|---|---|---|
| `domain:` | `domain:github.com` | Filtrer par domaine |
| `title:` | `title:python` | Rechercher uniquement dans le titre de la page |
| `url:` | `url:github` | Rechercher uniquement dans l'URL |
| `after:` | `after:2024-01-01` | Début de plage de dates (inclus) |
| `before:` | `before:2024-12-31` | Fin de plage de dates (inclus) |
| `browser:` | `browser:chrome` | Filtrer par type de navigateur |
| `device:` | `device:laptop` | Filtrer par nom ou UUID d'appareil |
| `is:bookmarked` | `is:bookmarked` | Uniquement les enregistrements marqués en favori |
| `has:note` | `has:note` | Uniquement les enregistrements avec des annotations |
| `tag:` | `tag:work` | Filtrer les favoris par tag |

#### Combinaison de Jetons

Les jetons et les mots-clés peuvent être combinés librement :
```
domain:arxiv.org after:2024-01-01 deep learning
is:bookmarked tag:work project management
browser:firefox -youtube after:2025-01-01
```

---

### `restore` — Restaurer depuis WebDAV

Restaurer la base de données depuis une sauvegarde WebDAV.

```bash
# Lister les sauvegardes et choisir de manière interactive
hsync restore

# Restaurer automatiquement la dernière sauvegarde (fusion)
hsync restore --latest

# Lister les sauvegardes disponibles en JSON
hsync restore --list

# Mode remplacement : écraser complètement la base de données locale
hsync restore --replace

# Restaurer également le cache de favicons
hsync restore --latest --restore-favicons
```

**Options :**

| Drapeau | Description |
|---|---|
| `--latest` | Utiliser automatiquement la sauvegarde la plus récente sans confirmation |
| `--list` | Lister les sauvegardes disponibles au format JSON et quitter |
| `--replace` | Mode remplacement : écraser la base de données locale au lieu de fusionner |
| `--restore-favicons` | Restaurer également le cache de favicons depuis la sauvegarde |

!!! info "Fusion vs Remplacement"
    Le comportement par défaut **fusionne** les enregistrements de sauvegarde avec votre base de données locale — les enregistrements des deux côtés sont conservés et dédupliqués. Utilisez `--replace` uniquement lorsque vous souhaitez écraser complètement les données locales avec la sauvegarde.

---

### `db` — Maintenance de la Base de Données

```bash
# VACUUM + ANALYZE (récupérer l'espace fragmenté)
hsync db vacuum

# Reconstruire l'index de recherche en texte intégral
hsync db rebuild-fts

# Normaliser les noms de domaine dans tous les enregistrements
hsync db normalize

# Afficher les statistiques de la base de données
hsync db stats
hsync db stats --json
```

**Sous-commandes :**

| Sous-commande | Description |
|---|---|
| `vacuum` | Exécuter `VACUUM` et `ANALYZE` — récupère l'espace fragmenté, met à jour les statistiques du planificateur de requêtes |
| `rebuild-fts` | Reconstruire l'index de recherche en texte intégral FTS5 — à utiliser si la recherche est lente ou si des résultats manquent |
| `normalize` | Recalculer les noms de domaine pour tous les enregistrements (utile après l'importation de bases de données brutes) |
| `stats` | Alias pour `hsync -S` |

---

### `config` — Gérer la Configuration

Lire et écrire des valeurs de configuration sans ouvrir l'interface graphique.

```bash
# Lister toutes les clés et leurs valeurs actuelles
hsync config list

# Lire une seule valeur
hsync config get webdav.url

# Écrire une valeur
hsync config set webdav.enabled true
hsync config set webdav.url https://dav.example.com/historysync/
hsync config set scheduler.sync_interval_hours 2
hsync config set theme dark
hsync config set language fr_FR
```

**Clés configurables :**

| Clé | Type | Description |
|---|---|---|
| `webdav.enabled` | bool | Activer la sauvegarde WebDAV |
| `webdav.url` | string | URL du serveur WebDAV |
| `webdav.username` | string | Nom d'utilisateur WebDAV |
| `webdav.remote_path` | string | Chemin distant pour les sauvegardes (par défaut : `/HistorySync/`) |
| `webdav.max_backups` | int | Nombre de sauvegardes à conserver (par défaut : `10`) |
| `webdav.verify_ssl` | bool | Vérifier le certificat SSL (par défaut : `true`) |
| `webdav.auto_backup` | bool | Activer la sauvegarde automatique planifiée |
| `webdav.backup_favicons` | bool | Inclure le cache de favicons dans la sauvegarde |
| `scheduler.auto_sync_enabled` | bool | Activer la synchronisation automatique des navigateurs |
| `scheduler.sync_interval_hours` | int | Intervalle de synchronisation en heures |
| `scheduler.auto_backup_enabled` | bool | Activer la sauvegarde WebDAV planifiée |
| `scheduler.auto_backup_interval_hours` | int | Intervalle de sauvegarde en heures |
| `scheduler.launch_on_startup` | bool | Démarrer HistorySync à la connexion |
| `theme` | string | `dark` \| `light` \| `system` |
| `language` | string | Code de langue de l'interface (ex. : `fr_FR`). Vide = détection automatique. |

---

<a id="update-check-for-updates"></a>

### `update` — Vérifier les Mises à Jour

Vérifiez si une nouvelle version de HistorySync est disponible pour la plateforme et le type d'installation actuels.

```bash
# Sortie lisible par un humain
hsync update

# Sortie JSON lisible par une machine
hsync update --json

# Vérifier un canal de publication non par défaut
hsync update --channel beta
hsync update --channel nightly
```

**Options :**

| Drapeau | Description |
|---|---|
| `--json` | Émettre les métadonnées de mise à jour en JSON pour les scripts et la CI |
| `--channel CH` | Remplacer le canal configuré pour cette vérification : `stable` \| `beta` \| `nightly` |

**Ce que fait la commande :**

- Utilise les mêmes métadonnées de mise à jour dépendantes de la plateforme que l'application desktop.
- Se rabat sur les métadonnées des releases GitHub si l'API de mise à jour principale est indisponible.
- Respecte votre forme d'installation actuelle lors du choix des artefacts, comme un installateur, une archive ZIP portable, une AppImage ou un `.dmg`.

!!! note "Les vérifications CLI ne font que vérifier"
    `hsync update` indique la disponibilité et les métadonnées. Le véritable flux guidé de téléchargement et d'installation se trouve dans **Paramètres → Mises à jour** de l'application desktop.

---

## Complétion du Shell

`hsync` prend en charge la complétion du shell via `argcomplete`.

=== "Bash"
    ```bash
    # Configuration globale unique
    activate-global-python-argcomplete --user

    # Ou ajouter à ~/.bashrc :
    eval "$(register-python-argcomplete hsync)"
    ```

=== "Zsh"
    ```zsh
    # Ajouter à ~/.zshrc :
    autoload -U bashcompinit && bashcompinit
    eval "$(register-python-argcomplete hsync)"
    ```

=== "Fish"
    ```fish
    register-python-argcomplete --shell fish hsync \
      > ~/.config/fish/completions/hsync.fish
    ```

---

## Exemples de Scripts et CI

```bash
# Synchroniser, puis vérifier le résultat
hsync -s -q && echo "sync ok" || echo "sync failed"

# Passer le JSON de statut à jq
hsync -S --json | jq .record_count

# Enregistrer le journal dans un fichier
hsync -s --no-color 2>&1 | tee sync.log

# Synchronisation + sauvegarde planifiée (compatible cron)
hsync -sb -q

# Exporter les pages GitHub de la semaine dernière en JSON
hsync -e github_week.json \
  --domain github.com \
  --after "$(date -d '7 days ago' +%Y-%m-%d)"

# Synchronisation sans interface depuis le module principal Python (pour les tâches planifiées)
python -m src.main --headless --sync
```

---

## Codes de Sortie

| Code | Signification |
|---|---|
| `0` | Succès |
| `1` | Erreur (détails imprimés sur stderr) |
