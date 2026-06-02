---
title: Démarrage Rapide
description: Lancez HistorySync en moins de cinq minutes — synchronisation automatique en arrière-plan, sauvegarde cloud et recherche Spotlight.
---

# Démarrage Rapide

Ce guide vous permet de passer de zéro à une sauvegarde entièrement automatisée de votre historique de navigation en **moins de cinq minutes**.

---

## Étape 1 — Premier Lancement

Démarrez HistorySync. Au premier lancement, un **assistant de configuration** vous guidera à travers les paramètres essentiels.

Si vous avez installé depuis les sources :
```bash
python -m src.main
```

---

## Étape 2 — Synchroniser vos Navigateurs

Dans le **Tableau de bord**, cliquez sur **Synchroniser maintenant**. HistorySync va :

1. Détecter automatiquement tous les navigateurs installés sur votre système.
2. Lire en toute sécurité leurs bases de données SQLite d'historique en utilisant des instantanés WAL — les navigateurs peuvent rester ouverts.
3. Importer les enregistrements dans la base de données locale de HistorySync.

!!! tip "La première synchronisation prend plus de temps"
    Si vous avez des années d'historique sur plusieurs navigateurs, la première synchronisation peut prendre une à deux minutes. Les synchronisations suivantes sont **incrémentielles** — seuls les nouveaux enregistrements sont importés.

### Synchronisation sélective

Pour synchroniser uniquement des navigateurs spécifiques, utilisez la CLI :
```bash
hsync -s --browsers chrome,firefox
```

---

## Étape 3 — Rechercher dans votre Historique

### Recherche dans l'Interface Graphique
Utilisez la barre de recherche en haut de l'onglet **Historique**. Pendant que vous tapez, les résultats apparaissent instantanément.

### Superposition Globale (Spotlight)
Appuyez sur <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>H</kbd> depuis **n'importe quelle application** pour afficher la superposition d'accès rapide. Fonctionne sur Windows, macOS et Linux (X11). Sous Wayland, associez `python -m src.main --quick` à un raccourci système à la place.

Tapez naturellement, ou utilisez le [DSL de Requête Avancé](cli-reference.md#query-dsl) :

| Exemple de requête | Ce qu'elle trouve |
|---|---|
| `python async` | Pages contenant ces mots dans le titre ou l'URL |
| `domain:github.com` | Uniquement les pages GitHub |
| `after:2024-06-01 domain:arxiv.org` | Articles lus après juin 2024 |
| `is:bookmarked tag:work` | Pages marquées en favori avec le tag « work » |
| `react -tutorial` | Pages React, en excluant les tutoriels |

---

## Étape 4 — Activer la Synchronisation Automatique

Allez dans **Paramètres → Synchronisation automatique** et :

1. Activez la **Synchronisation automatique**.
2. Définissez votre intervalle préféré (par défaut : 2 heures).
3. Activez **Lancer au démarrage du système** pour que HistorySync démarre silencieusement en arrière-plan.

Désormais, votre historique de navigation est continuellement fusionné dans une base de données unique et interrogeable — automatiquement.

---

## Étape 5 — Configurer la Sauvegarde Cloud (Optionnel)

La sauvegarde WebDAV vous permet de restaurer votre historique sur une nouvelle machine ou de le partager entre appareils.

1. Allez dans **Paramètres → Sauvegarde Cloud WebDAV**.
2. Entrez l'URL de votre serveur WebDAV, votre nom d'utilisateur et votre mot de passe.
3. Activez la **Sauvegarde automatique** et définissez un intervalle.
4. Cliquez sur **Tester la connexion** pour vérifier.

Consultez le [guide de configuration WebDAV](webdav-setup.md) pour une liste de fournisseurs compatibles avec des instructions étape par étape.

---

## Étape 6 — Activer la Vérification des Mises à Jour

Allez dans **Paramètres → Mises à jour** et choisissez comment vous voulez que HistorySync gère les nouvelles versions :

1. Laissez **Vérifier automatiquement les mises à jour** activé si vous souhaitez recevoir des rappels passifs.
2. Choisissez un canal de publication comme **Stable** ou **Bêta**.
3. Définissez une politique de rappel, par exemple une fois par semaine au lieu de chaque lancement.
4. Utilisez **Vérifier les mises à jour** à tout moment pour lancer une vérification à la demande.

Lorsqu'une version plus récente est disponible, HistorySync peut afficher une bannière, ouvrir une boîte de dialogue détaillée sur la version, et mémoriser vos choix comme « me le rappeler plus tard » ou « ignorer cette version ».

---

## Étape 7 — Mode Barre des Tâches (Fonctionnement en Arrière-plan)

Une fois configuré, fermez la fenêtre principale. HistorySync se réduit dans la **barre des tâches système** et continue de synchroniser et de sauvegarder silencieusement.

Faites un clic droit sur l'icône de la barre des tâches pour :

- **Ouvrir HistorySync** — ramener la fenêtre principale.
- **Synchroniser maintenant** — déclencher une synchronisation immédiate.
- **Sauvegarder maintenant** — déclencher une sauvegarde WebDAV immédiate.
- **Quitter** — arrêter complètement l'application.

---

## Prochaines Étapes

| Ce que vous voulez faire | Où aller |
|---|---|
| Automatiser les synchronisations depuis le terminal | [Référence CLI](cli-reference.md) |
| Vérifier les nouvelles versions depuis le terminal | [Référence CLI](cli-reference.md#update-check-for-updates) |
| Configurer un fournisseur WebDAV spécifique | [Configuration WebDAV](webdav-setup.md) |
| Personnaliser les raccourcis clavier | [Raccourcis Clavier](keyboard-shortcuts.md) |
| Exporter votre historique en CSV / JSON / HTML | [Référence CLI — Exporter l'Historique](cli-reference.md#export) |
| Comprendre le modèle de sécurité | [Architecture de Sécurité](../dev/security.md) |
