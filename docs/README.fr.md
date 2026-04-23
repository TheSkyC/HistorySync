<div align="center">

![HistorySync Logo](https://img.shields.io/badge/HistorySync-409EFF?style=for-the-badge&logo=sync)

![GitHub release (latest by date)](https://img.shields.io/github/v/release/TheSkyC/HistorySync?style=flat-square)
![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)
![Python Version](https://img.shields.io/badge/Python-3.10%2B-blue?style=flat-square&logo=python)
</div>
<p align="center">
  <a href="../README.md">English</a> | 
  <a href="./README.zh-CN.md">简体中文</a> | 
  <a href="./README.zh-TW.md">繁體中文</a> | 
  <a href="./README.ja.md">日本語</a> | 
  <a href="./README.ko.md">한국어</a> | 
  <a href="./README.ru.md">Русский</a> | 
  Français
<br></p>

# HistorySync
**HistorySync** est une puissante application de bureau multiplateforme. Elle fournit une solution complète et efficace pour la gestion unifiée de l'historique des navigateurs et la sauvegarde dans le cloud. De l'agrégation de données multi-navigateurs à la recherche plein texte en quelques millisecondes, en passant par les sauvegardes WebDAV automatisées et les statistiques riches, elle vous donne un contrôle total sur vos données de navigation.

Elle prend en charge nativement les bases de données sous-jacentes des navigateurs basés sur Chromium, Firefox et Safari, offrant une protection exceptionnelle de la confidentialité et une expérience de gestion locale fluide.

---

## 📥 Télécharger
Vous pouvez télécharger les dernières versions pour Windows, macOS et Linux sur la page **[GitHub Releases](https://github.com/TheSkyC/HistorySync/releases/latest)**.

[![GitHub release (latest by date)](https://img.shields.io/github/v/release/TheSkyC/HistorySync?style=for-the-badge)](https://github.com/TheSkyC/HistorySync/releases/latest)

## 🚀 Fonctionnalités principales

### 📂 Agrégation de données omnipotente (Plus de 30 navigateurs)
*   **Compatibilité massive** : Prend en charge nativement Chrome, Edge, Firefox, Safari, Brave, Vivaldi, Arc et de nombreux navigateurs régionaux/personnalisés (QQ, Sogou, CentBrowser, etc.).
*   **Extraction incrémentielle intelligente** : Lit en toute sécurité les instantanés SQLite WAL, permettant une extraction sans perte et sans conflit même pendant que vos navigateurs sont en cours d'exécution.
*   **Importation de base de données portable** : Importez manuellement des fichiers `History` ou `places.sqlite` autonomes pour fusionner facilement les données d'anciens ordinateurs.

### 🔍 Recherche rapide style Spotlight et base de connaissances
*   **Superposition d'accès rapide** : Appuyez sur `Ctrl+Shift+H` n'importe où pour faire apparaître une superposition de recherche minimaliste.
*   **Nouveau moteur de raccourcis** : Un système de raccourcis multiplateforme basé sur `pynput`, offrant 14 raccourcis globaux et intégrés hautement personnalisables.
*   **Syntaxe de requête avancée** : Recherchez comme un pro en utilisant des jetons (par exemple, `domain:github.com`, `after:2024-01-01`).
*   **Signets et annotations** : Transformez votre historique en base de connaissances. Ajoutez des balises et des notes en texte enrichi aux pages importantes.

### ⚡ Performances extrêmes et interface moderne
*   **Défilement fluide sur des millions d'enregistrements** : La logique de pagination réécrite introduit la pagination en deux étapes et les index Keyset. Les recherches par expression régulière sont poussées vers la couche SQL, éliminant complètement les saccades.
*   **Interface adaptative** : La distribution proportionnelle de la largeur des colonnes assure un redimensionnement fluide de la fenêtre. Prend en charge le basculement en temps réel entre les thèmes Sombre/Clair du système.
*   **Visualisation riche des données** : Comprenez vos habitudes grâce à une carte thermique quotidienne, des graphiques circulaires et des barres d'activité sur 24 heures.

### ☁️ Synchronisation Cloud et automatisation
*   **Sauvegarde et fusion WebDAV** : Utilise des **téléchargements en continu atomiques**. Lors de la restauration depuis le cloud, le système fusionne intelligemment les enregistrements sur plusieurs appareils.
*   **CLI Headless (`hsync`)** : Un outil en ligne de commande complet pour les utilisateurs avancés.
*   **Mode arrière-plan silencieux** : S'exécute réduit dans la barre d'état système, effectuant automatiquement les extractions et les sauvegardes planifiées.

### 🛡️ Confidentialité et contrôle ultimes
*   **Mode caché et masquage souple** : Une vue dédiée "Enregistrements cachés". Prend en charge le masquage souple de domaines spécifiques (les enregistrements restent dans la base de données mais disparaissent de la vue principale).
*   **Architecture de sécurité V2** : Protège les configurations sensibles à l'aide de sous-clés de chiffrement et d'authentification HKDF indépendantes.
*   **Liste noire de domaines** : Bloquez des domaines spécifiques en un clic.

## 📸 Captures d'écran

*Aperçu du tableau de bord*

<img width="1000" alt="Dashboard" src="assets/ui-dashboard.png" />

<details>
<summary><b>► Cliquez pour voir plus de captures d'écran</b></summary>

*Statistiques et carte thermique*

<img width="1000" alt="Statistics" src="assets/ui-stats.png" />

*Recherche et gestion de l'historique*

<img width="1000" alt="History" src="assets/ui-history.png" />

</details>

## 🛠️ Configuration de l'environnement de développement

### Prérequis
*   Python 3.10 ou supérieur
*   Git (facultatif, pour cloner le dépôt)

### Étapes
1.  **Cloner le dépôt (ou télécharger le ZIP)**
    ```bash
    git clone https://github.com/TheSkyC/HistorySync.git
    cd HistorySync
    ```

2.  **Créer et activer un environnement virtuel (Recommandé)**
    ```bash
    python -m venv venv
    # Windows
    .\venv\Scripts\activate
    # macOS/Linux
    source venv/bin/activate
    ```

3.  **Installer les dépendances**
    ```bash
    pip install -r requirements.txt
    ```

4.  **Exécuter**
    ```bash
    python -m src.main
    ```

## 🚀 Démarrage rapide

HistorySync offre des modes de fonctionnement flexibles :

### 1. 🔄 Mode arrière-plan silencieux (Recommandé)
*Idéal pour les utilisateurs qui souhaitent "configurer et oublier" pour des sauvegardes automatisées.*
1.  **Démarrage** : Allez dans `Paramètres > Démarrage` et activez "Lancer au démarrage du système".
2.  **Planification** : Définissez votre intervalle d'extraction sous `Synchronisation automatique`.
3.  **Cloud** : Entrez vos identifiants WebDAV et activez la sauvegarde automatique.
4.  **Exécuter** : Fermez la fenêtre principale. L'application se réduira dans la barre d'état.

### 2. 🔍 Mode de gestion active
*Idéal pour les utilisateurs qui recherchent fréquemment dans l'historique, annotent des pages ou effacent des données de confidentialité.*
1.  **Recherche rapide** : Appuyez sur `Ctrl+Shift+H` n'importe où pour appeler la superposition.
2.  **Base de connaissances** : Ajoutez des pages importantes aux signets et ajoutez des notes.
3.  **Confidentialité** : Sélectionnez les enregistrements indésirables et supprimez-les, ou choisissez "Mettre le domaine sur liste noire".

## 🌐 Langues prises en charge
Cet outil prend en charge les interfaces utilisateur suivantes :
*   **English** (`en_US`)
*   **简体中文** (`zh_CN`)
*   **繁體中文** (`zh_TW`)
*   **日本語** (`ja_JP`)
*   **한국어** (`ko_KR`)
*   **Français** (`fr_FR`)
*   **Deutsch** (`de_DE`)
*   **Русский** (`ru_RU`)
*   **Español** (`es_ES`)
*   **Italiano** (`it_IT`)

## 🤝 Contribution
Toute forme de contribution est la bienvenue ! Si vous avez des questions, des suggestions de fonctionnalités ou si vous trouvez un bug, n'hésitez pas à les soumettre via les GitHub Issues.

## 📄 Licence
Ce projet est open-source sous la licence [Apache 2.0](../LICENSE), permettant une utilisation, une modification et une distribution libres, à condition que l'avis de droit d'auteur soit conservé.

## 📞 Contact
- Auteur : TheSkyC
- Email : 0x4fe6@gmail.com