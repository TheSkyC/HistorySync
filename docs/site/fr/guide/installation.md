---
title: Installation
description: Comment installer HistorySync sur Windows, macOS et Linux — paquets pré-compilés et installation depuis les sources.
---

# Installation

HistorySync fonctionne sur **Windows**, **macOS** et **Linux**. Choisissez la méthode qui vous convient le mieux.

---

## Paquets Pré-compilés (Recommandé)

Téléchargez la dernière version depuis la page **[GitHub Releases](https://github.com/TheSkyC/HistorySync/releases/latest)**.

=== "Windows"

    | Paquet | Remarques |
    |---|---|
    | `HistorySync-vX.Y.Z-windows-x64-setup.exe` | Installateur complet, ajoute une entrée dans le menu Démarrer et démarrage automatique optionnel |
    | `HistorySync-vX.Y.Z-windows-x64-portable.zip` | Portable — extrayez et exécutez n'importe où, aucune installation nécessaire |

    Lancez l'installateur et suivez les instructions à l'écran. Aucune dépendance supplémentaire n'est requise.

=== "macOS"

    | Paquet | Remarques |
    |---|---|
    | `HistorySync-vX.Y.Z-macos-arm64.dmg` | Installation par glisser-déposer |

    1. Ouvrez le fichier `.dmg`.
    2. Faites glisser **HistorySync** dans votre dossier `Applications`.
    3. Au premier lancement, macOS peut afficher une invite de sécurité — cliquez sur **Ouvrir** pour continuer.

    !!! note "Permission Accessibilité"
        Le raccourci global `Ctrl+Shift+H` nécessite la permission **Accessibilité**. macOS vous en fera la demande la première fois que vous l'utiliserez. Accordez l'accès dans **Réglages Système → Confidentialité et sécurité → Accessibilité**.

=== "Linux"

    | Paquet | Remarques |
    |---|---|
    | `HistorySync-vX.Y.Z-linux-x86_64.AppImage` | Fonctionne sur toutes les distributions Linux modernes |
    | `HistorySync-vX.Y.Z-linux-x86_64.tar.gz` | Archive tar générique pour toute distribution Linux |
    | `historysync_X.Y.Z_amd64.deb` | Pour les distributions basées sur Debian/Ubuntu |

    **AppImage :**
    ```bash
    chmod +x HistorySync-*.AppImage
    ./HistorySync-*.AppImage
    ```

    **Debian/Ubuntu `.deb` :**
    ```bash
    sudo dpkg -i HistorySync-*.deb
    sudo apt-get install -f   # corriger les dépendances manquantes
    ```

    !!! warning "Raccourcis globaux sur Linux/Wayland"
        Les raccourcis globaux via `pynput` ne sont **pas pris en charge sur Wayland**. Le raccourci de superposition `Ctrl+Shift+H` ne fonctionnera pas dans une session Wayland. Envisagez d'utiliser `--quick` avec un raccourci au niveau système comme solution de contournement (voir [Raccourcis Clavier](keyboard-shortcuts.md)).

---

## Installation depuis les Sources

Utilisez cette méthode si vous souhaitez exécuter le dernier code de développement ou contribuer au projet.

### Prérequis

- **Python 3.10+** (Python 3.12 recommandé — correspond à la CI)
- **Git**

### Étapes

```bash
# 1. Cloner le dépôt
git clone https://github.com/TheSkyC/HistorySync.git
cd HistorySync

# 2. Créer et activer un environnement virtuel (fortement recommandé)
python -m venv venv

# Windows
.\venv\Scripts\activate

# macOS / Linux
source venv/bin/activate

# 3. Installer les dépendances d'exécution
pip install -r requirements.txt

# 4. Lancer l'application
python -m src.main
```

### Installer la CLI `hsync` (optionnel)

Des binaires `hsync` pré-compilés sont disponibles sur la page **[GitHub Releases](https://github.com/TheSkyC/HistorySync/releases/latest)** :

| Paquet | Plateforme |
|---|---|
| `hsync-vX.Y.Z-windows-x64-setup.exe` | Installateur Windows |
| `hsync-vX.Y.Z-windows-x64.zip` | Windows portable |
| `hsync-vX.Y.Z-macos-arm64.tar.gz` | macOS (Apple Silicon) |
| `hsync-vX.Y.Z-linux-x86_64.tar.gz` | Linux x86-64 |

La CLI sans interface graphique peut également être invoquée directement avec Python :

```bash
python -m src.cli --help
```

Pour l'installer comme commande `hsync` dans votre `PATH` :

```bash
# Créer un script wrapper simple (Linux / macOS)
echo '#!/bin/sh\npython -m src.cli "$@"' > /usr/local/bin/hsync
chmod +x /usr/local/bin/hsync
```

---

## Vérification de l'Installation

Lancez l'interface graphique et vérifiez le numéro de version dans la barre de titre, ou exécutez :

```bash
# Interface graphique
python -m src.main --version

# CLI
python -m src.cli --version
# ou si installé :
hsync --version
```

---

## Mise à Jour

Remplacez le binaire existant par le nouveau depuis la page Releases. HistorySync stocke sa configuration et sa base de données séparément du binaire de l'application, donc la mise à jour ne touche jamais vos données.

À partir de la version 1.4.0, les builds desktop packagés incluent aussi un **système de mise à jour intégré** :

- Les **builds installateur Windows** peuvent généralement déléguer directement le processus au programme d'installation.
- Les **builds macOS `.dmg`** peuvent télécharger et ouvrir l'image disque pour vous.
- Les **installations portables, AppImage et par archive** téléchargent l'artefact vérifié correspondant et l'affichent afin que vous puissiez remplacer le binaire en toute sécurité.
- Les **installations gérées par le système** comme les paquets `.deb` continuent de s'appuyer sur votre gestionnaire de paquets ou sur la page Releases.

Vous pouvez lancer cela depuis **Paramètres → Mises à jour → Vérifier les mises à jour**, ou depuis la bannière de mise à jour lorsqu'une nouvelle version est détectée.

Si vous préférez le terminal, utilisez :

```bash
hsync update
hsync update --json
hsync update --channel beta
```

Emplacements par défaut des données :

| Plateforme | Répertoire |
|---|---|
| Windows | `%APPDATA%\HistorySync\` |
| macOS | `~/Library/Application Support/HistorySync/` |
| Linux | `~/.config/HistorySync/` |

Vous pouvez remplacer cela avec `--config-dir` ou utiliser le mode `--portable` pour conserver toutes les données à côté de l'exécutable.

!!! tip "Installations portables"
    Les installations portables et les configurations basées sur un marqueur `.portable` conservent la configuration et les bases de données à côté de l'exécutable. Le système de mise à jour préserve ce modèle et choisit si possible des artefacts de publication au format portable.

---

## Désinstallation

1. Supprimez le binaire de l'application / AppImage / paquet.
2. Supprimez éventuellement le répertoire de données ci-dessus pour effacer toutes les données de navigation et les paramètres.

!!! warning
    La suppression du répertoire de données est irréversible. Sauvegardez votre base de données au préalable si vous souhaitez conserver votre historique.
