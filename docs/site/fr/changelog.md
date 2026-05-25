---
title: Journal des modifications
description: Historique des versions et changements notables de HistorySync.
---

# Journal des modifications

Tous les changements notables sont documentés ici. Le format est basé sur [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), et ce projet suit la [gestion sémantique de version](https://semver.org/spec/v2.0.0.html).

---

## [Non publié]

*Changements présents sur `main` mais pas encore inclus dans une version taguée.*

---

## [1.3.2] - 2026-05-25

### Ajouté
- Les versions stables sont désormais également répliquées vers R2 pour une distribution plus résiliente.

### Modifié
- La sauvegarde automatique après synchronisation est désormais désactivée par défaut.

### Corrigé
- Correction d'une condition de concurrence dans le nettoyage des threads du planificateur pouvant affecter la stabilité de la synchronisation.
- `hsync db normalize` demande désormais une confirmation explicite avant d'appliquer les changements.
- La synchronisation CLI libère désormais les ressources de la base de données de manière plus fiable.
- Les jetons IPC d'instance unique sont maintenant isolés par compte utilisateur.

### Documentation
- Mise à jour de l'identité visuelle du site de documentation, des informations de contact et des pages localisées.
- Ajout d'une politique de sécurité dédiée.

### Tests
- Extension de la couverture automatisée pour le planificateur, les viewmodels et les flux WebDAV.

---

## [1.3.1] - 2026-05-19

### Corrigé
- L'export par expression régulière n'est plus limité à 100 000 enregistrements ; remplacé par une pagination par curseur pour les exports volumineux complets.
- L'interface ne se fige plus pendant une recherche d'historique par expression régulière ; le scan est déplacé dans un thread en arrière-plan.
- Les calculs de plage temporelle mensuelle ne dérivent plus lors des transitions DST (heure d'été).
- Le filtre de domaines masqués échappe désormais correctement les caractères génériques LIKE dans les noms de domaine.
- Le comptage des enregistrements par préfixe URL ne double-compte plus les préfixes chevauchants.
- Les échecs de nettoyage WebDAV sont désormais remontés au lieu d'être ignorés silencieusement ; l'horodatage du manifeste est aligné sur l'heure d'upload.
- L'export HTML génère maintenant une erreur quand le marqueur d'injection est absent du template, au lieu de produire un fichier corrompu.
- La sauvegarde de la configuration est supprimée à l'arrêt pour éviter toute corruption ; les promotions de configuration échouées sont maintenant annulées proprement.
- La rotation des sauvegardes de configuration est corrigée ; une protection contre les faux positifs de détection de migration a été ajoutée.
- Le chargement des données de badge gère désormais les erreurs de base de données sans planter.
- Le thread de sauvegarde de l'extracteur ne bloque plus implicitement le processus principal à l'arrêt.
- Résolution d'un potentiel interblocage lors de l'export d'une base de données sans FTS.

### Build
- L'import caché WebDAV dans la spec PyInstaller est corrigé de `webdav4` vers `webdav3`, résolvant les erreurs de module manquant dans les builds packagés.

---

## [1.3.0] - 2026-05-14

### Ajouté
- Le thème par défaut est passé de Sombre à Système, afin que l'application suive l'apparence de l'OS dès le départ.
- Aperçu du nombre d'enregistrements dans les boîtes de dialogue de gestion de la liste noire et des domaines masqués, afin d'afficher l'impact avant confirmation.
- Historique de recherche récent isolé pour le mode regex, pour garder les flux de recherche avancée plus propres.
- Icône de l'application repensée avec un rendu de zone de notification animé basé sur SVG remplaçant les ressources statiques.
- Site de documentation MkDocs multilingue.

### Corrigé
- Les déclencheurs FTS perdus silencieusement après un crash du processus sont désormais restaurés avant tous les chemins d'écriture de l'historique.
- Les jetons de recherche `title:` et `url:` ne s'écrasent plus mutuellement ; les requêtes multi-mots sur un champ sont désormais découpées en termes AND correctement.
- Les domaines masqués sont désormais correctement filtrés dans la recherche rapide de l'overlay.
- Condition de frontière temporelle corrigée pour l'extraction incrémentielle de Safari.
- Suppression du filtre de chemin incorrect dans le scanner de navigateurs qui excluait les installations non standard.
- Le texte chiffré du mot de passe WebDAV est désormais préservé lorsqu'un déchiffrement échoue au chargement de la configuration.
- Le démarrage en instance unique retombe désormais en sécurité si l'écriture du fichier jeton échoue.
- Les enregistrements d'historique sont désormais correctement migrés lors de l'adoption d'une identité d'appareil précédente.
- Le signal `sync_progress` est désormais protégé contre les mauvais types d'arguments émis depuis le thread de travail.
- La progression de synchronisation en temps réel a été restaurée ; la durée de vie du wrapper QThread a été renforcée contre les plantages destroyed-while-running.
- Le cycle de vie du thread de sauvegarde a été corrigé et les exceptions d'auto-sauvegarde sont désormais isolées du flux de synchronisation.
- Les courses d'émission de signaux inter-threads et les problèmes de durée de vie de QThread pendant la synchronisation ont été résolus.
- Les déclencheurs FTS sont désormais restaurés immédiatement après une exception d'upsert pour refermer la fenêtre d'écriture.
- `_ro_lock` est désormais maintenu pendant les deux phases de requête dans `get_records` afin d'éliminer la course de connexion.
- Le manifeste de synchronisation WebDAV est désormais téléversé avant le nettoyage des anciennes sauvegardes afin d'éviter un manifeste obsolète en cas de crash.
- Les écritures dans le cache de domaines sont désormais protégées par un verrou pour éviter une course TOCTOU.
- Le cache de page obsolète est désormais évincé dans le chemin regex load-more pour éviter les lignes vides.
- Le flash des boîtes de dialogue dans le coin supérieur gauche lors de la première ouverture a été éliminé.
- La taille de police de l'autocomplétion est désormais bornée à une plage valide sous Linux.
- La réduction dans la zone de notification est désormais empêchée lorsque cette zone n'est pas disponible.

### Performance
- Le nettoyage O(N) de `vt_cache` a été remplacé par une éviction LRU à granularité de page.
- Le verrou d'écriture est désormais libéré avant `VACUUM INTO` dans `export_without_fts`.
- Le registre partagé et les ensembles de filtres dans l'extractor manager sont désormais protégés par un verrou pour éviter les courses de données.

### Build
- Ajout d'un repli de plateforme Qt sous Linux ; les dépendances xcb sont empaquetées pour un démarrage immédiat sous Linux.
- Ajout de règles `.gitattributes` complètes pour les fins de ligne et les fichiers binaires.

---

## [1.2.2] - 2026-04-29

### Corrigé
- La commande CLI `restore` restaurait toujours la dernière sauvegarde au lieu de celle choisie par l'utilisateur.
- La commande CLI `restore` ne respectait pas l'option de restauration des favicons.
- `CLI restore --replace` utilisait un remplacement de base de données non sûr.
- Les temporisateurs d'amorce du planificateur n'étaient pas annulés, ce qui faisait déclencher d'anciens callbacks après replanification.
- L'utilisation de l'API de taille du terminal a été corrigée, ce qui rétablit le formatage de sortie dans toutes les commandes CLI.

---

## [1.2.1] - 2026-04-23

### Ajouté
- Bouton « Localiser dans l'historique » sur les cartes de favoris pour une navigation rapide.
- Cliquer sur la zone d'étiquette ou de note d'une carte de favori ouvre désormais directement l'éditeur.

### Corrigé
- Les conflits des raccourcis globaux `Ctrl+F` / `Ctrl+R` ont été résolus ; les raccourcis fonctionnent désormais de façon fiable dans la vue historique.
- Les compteurs de visites des séparateurs de date respectent désormais les filtres actuels et le mode d'affichage des enregistrements masqués.

---

## [1.2.0] - 2026-04-23

### Ajouté
- 14 raccourcis clavier globaux et internes configurables avec un panneau de paramètres dédié.
- Mode d'affichage des enregistrements masqués : une vue dédiée aux enregistrements masqués de manière logicielle.
- Masquage logiciel par domaine : possibilité de masquer tous les enregistrements d'un domaine sans les supprimer, avec une interface de gestion dédiée.
- Mode portable : détection automatique d'un fichier marqueur `.portable` à la racine de l'application et redirection de toutes les données vers le sous-répertoire `data/`.
- Entrée « Search the Web » dans l'overlay d'accès rapide et dans la liste d'autocomplétion, avec des préréglages de moteurs de recherche configurables.
- Option de démarrage « Lancer réduit dans la zone de notification ».
- Mode de réduction différée dans la zone de notification : fenêtre et sous-systèmes différés jusqu'à la première ouverture.
- Les séparateurs de date sont désormais restaurés après le basculement ou la réorganisation des colonnes.
- Suivi en temps réel du mode Sombre/Clair du système.

### Modifié
- Les téléversements WebDAV sont passés d'un mode chunked à un flux atomique pour une fiabilité nettement meilleure et l'élimination des fuites de descripteurs temporaires sous Windows.
- Le mode headless ignore désormais les sous-systèmes GUI et utilise un cache SQLite plus faible, réduisant l'empreinte mémoire en arrière-plan.
- L'éviction du cache de domaines et d'icônes est passée d'un `clear()` complet à un `popitem()` FIFO pour éliminer les pics périodiques d'éviction.
- Les bascules de visibilité des colonnes ont été déplacées dans un sous-menu pour une barre d'outils plus propre.

### Corrigé
- Les incohérences WAL en lecture après écriture ont été résolues en unifiant l'ordre des verrous du cycle de vie des connexions.
- Le crash de VACUUM provoqué par `prune_tombstones` pendant `_vacuuming=True` a été corrigé.
- Les tombstones sont désormais purgées pendant VACUUM afin d'éviter une croissance sans borne de la table.
- Les saccades de défilement après suppression/masquage/démasquage ont été corrigées ; la position de défilement est désormais préservée au lieu de revenir en haut.
- Les titres longs ne repoussent plus les boutons d'action hors de l'écran dans les cartes de paramètres.
- La barre de défilement horizontale parasite après changement de thème a été éliminée.
- Les lectures de favoris et d'annotations voient désormais immédiatement les données fraîches après une écriture (instantané WAL obsolète corrigé).
- Les points de jonction Windows ne sont plus traversés lors du scan BFS des navigateurs.
- L'intervalle de `QTimer` est désormais borné à `INT32_MAX` pour éviter un dépassement d'entier sur les très longs intervalles.
- `BrowserMonitor` est désormais correctement arrêté à la fermeture de l'application.
- Les requêtes de recherche CLI à plusieurs mots sont désormais acceptées sans guillemets.
- Les longues sorties tabulaires dans la CLI sont désormais tronquées avec une ellipse pour éviter le dépassement de ligne.
- Les échecs de `encrypt_text` sont désormais propagés au lieu d'ignorer silencieusement le mot de passe WebDAV.
- `get_bookmarked_urls` utilise désormais `DISTINCT` pour éviter les URL dupliquées dans les résultats.

### Performance
- La pagination par keyset en deux étapes dans `get_records` élimine le scan offset O(N) pour les historiques volumineux.
- La pagination de recherche regex a été déplacée au niveau SQL, éliminant le scan O(N) de la table entière.
- Les ralentissements de défilement rapide ont été réduits en optimisant les chemins chauds de paint, `data()`, d'analyse d'URL et de `eventFilter`.
- Les mises à jour d'état des navigateurs sur `DashboardPage` sont désormais ignorées lorsque la fenêtre est cachée.

### Sécurité
- Le chiffrement a été mis à niveau vers le format V2 avec des sous-clés HKDF indépendantes pour le chiffrement et l'authentification.
- Une authentification basée sur nonce a été ajoutée à l'IPC d'instance unique pour éviter les attaques par rejeu.
- Une faille XSS dans l'export HTML a été corrigée : les icônes SVG sont désormais assainies avant intégration.
- Le délai d'inactivité du mot de passe maître utilise désormais `time.time()` pour compter correctement pendant la mise en veille du système.
- Les contournements du mot de passe maître ont été fermés ; l'interface de session obsolète a été corrigée.

### Build
- Ajout d'un artefact autonome `tar.gz` pour macOS.
- Ajout d'une archive ZIP portable et d'un installateur Windows.
- Le runtime Python autonome Windows est désormais mis en cache dans la CI pour réduire les temps de build.

---

## [1.1.1] - 2026-04-12

### Corrigé
- Le décalage vertical de l'overlay (`Ctrl+Shift+H`) à la réouverture a été corrigé.
- La barre de défilement horizontale apparaissant aléatoirement dans le tableau d'historique a été corrigée.
- Le non-rafraîchissement de la page des favoris après modification depuis la page Historique a été corrigé.
- Le timestamp `bookmarked_at` qui ne se mettait pas à jour en cas de conflit a été corrigé.
- Une course potentielle lors de l'initialisation du client WebDAV a été corrigée.
- Les faux positifs de filtre dus à un `_excl_cache` non vidé après réinitialisation de connexion ont été corrigés.

### Performance
- Les requêtes d'historique et le chargement des badges de favoris/annotations ont été déplacés vers un thread d'arrière-plan pour ne plus bloquer l'interface.
- Le domaine d'affichage est désormais résolu via une jointure sur la table `domains` au lieu d'analyser l'URL à chaque ligne sur le chemin de rendu.
- Le second VACUUM redondant a été supprimé de `export_without_fts`.
- La sous-requête `NOT IN` sur `hidden_records` a été remplacée par une recherche corrélée `NOT EXISTS` plus efficace.

---

## [1.1.0] - 2026-04-11

### Ajouté
- Overlay de recherche rapide global de type Spotlight (`Ctrl+Shift+H`) : recherche instantanée dans l'historique, les favoris et les annotations depuis n'importe quelle application.
- Syntaxe de recherche avancée : `domain:`, `after:`, `before:`, `title:`, `url:`, `browser:`, `device:`, `is:bookmarked`, `has:note`, `tag:`.
- Autocomplétion en texte fantôme intégrée et suggestions fuzzy dans la barre de recherche.
- Page de statistiques avec heatmap annuelle de type GitHub (avec surbrillance du contour du mois actif), graphique circulaire d'utilisation des navigateurs, histogramme d'activité sur 24 heures et export d'image haute résolution en un clic.
- Système de favoris et d'annotations : étiquetez des URL et rédigez des notes enrichies pour constituer une base de connaissances personnelle.
- CLI headless `hsync` avec commandes `sync`, `backup`, `search`, `export`, `restore`, `config`, `db` et mode de surveillance.
- Complétion shell pour `hsync` via `argcomplete` (Bash, Zsh, Fish).
- Gestion de l'identité de l'appareil : renommer des appareils, supprimer ceux devenus obsolètes ou adopter une identité précédente après une réinstallation de l'OS.
- La restauration WebDAV fusionne désormais avec les données locales au lieu d'écraser de manière destructive.
- Export d'URL par glisser-déposer natif depuis le tableau d'historique (`Alt`+glisser ou glisser du favicon) vers le bureau ou les éditeurs.
- Bulle temporelle de défilement : affiche la date, le domaine principal et une barre de densité d'activité lors du glissement de la barre de défilement.
- Ajout de la prise en charge native de QQ Browser, Sogou, Twinkstar, CentBrowser, 2345 Explorer, Liebao, UC Browser (Desktop), Quark.
- Ajout de la prise en charge des dérivés Firefox : Waterfox, LibreWolf, Pale Moon, Basilisk, SeaMonkey.
- Prise en charge des canaux Canary/Dev/Beta de Chrome, Edge et Brave.
- Scan BFS approfondi pour détecter automatiquement les installations portables ou non standard de navigateurs.
- Animation de fondu à l'ouverture/fermeture de l'overlay.
- Assistant de première exécution remanié pour une configuration initiale plus simple.
- Assistant de migration pour une migration sans perte depuis les installations v1.0.x.
- Menu contextuel de la barre de défilement pour les modes d'affichage de la bulle temporelle.
- Animation inertielle fluide sur la bulle temporelle de défilement.

### Corrigé
- Les problèmes de verrouillage de fichiers pendant la sauvegarde WebDAV sous Windows ont été résolus.
- Le saut de position de la barre de défilement lors du changement de thème Sombre/Clair a été corrigé.
- Les requêtes FTS à plusieurs mots utilisent désormais une sémantique AND pour une meilleure précision.
- La requête UPDATE de `normalize_domains` est désormais traitée par lots de 5000 lignes pour éviter de longs verrous d'écriture.
- Les enregistrements masqués sont exclus des statistiques analytiques et de la recherche rapide de l'overlay.
- `_ensure_conn` est désormais protégé par le drapeau `_vacuuming` afin d'éviter tout accès concurrent pendant VACUUM.

### Performance
- L'extraction SQLite a été réécrite avec des insertions par lots et une regex précompilée, réduisant l'utilisation mémoire et améliorant la vitesse.
- Le rendu des favicons a été optimisé avec un cache LRU et une recoloration SVG, éliminant les saccades lors du défilement rapide.
- Le chargement initial de la page d'historique utilise une initialisation progressive pour réduire le temps avant le premier rendu.

---

## [1.0.0] - 2026-03-24

Version stable initiale.

### Ajouté
- Agrégation de l'historique de navigation depuis les navigateurs basés sur Chromium (Chrome, Edge, Brave, Opera, Vivaldi, Arc et plus), basés sur Firefox et Safari.
- Base de données SQLite locale avec recherche plein texte FTS5 utilisant un tokenizer trigram pour une recherche par sous-chaîne en quelques millisecondes.
- Sauvegarde et restauration WebDAV avec compression ZIP et vérification d'intégrité SHA-256.
- Prise en charge multi-navigateurs et multi-profils avec copie de base de données compatible WAL.
- Défilement virtuel pour parcourir fluidement des listes d'historique contenant des millions d'enregistrements.
- Intégration à la zone de notification avec notifications d'état de synchronisation.
- Chiffrement par mot de passe maître pour les identifiants WebDAV via HKDF-SHA256 et intégration au trousseau système.
- Paquets Windows et macOS.

[Unreleased]: https://github.com/TheSkyC/HistorySync/compare/v1.3.2...HEAD
[1.3.2]: https://github.com/TheSkyC/HistorySync/compare/v1.3.1...v1.3.2
[1.3.1]: https://github.com/TheSkyC/HistorySync/compare/v1.3.0...v1.3.1
[1.3.0]: https://github.com/TheSkyC/HistorySync/compare/v1.2.2...v1.3.0
[1.2.2]: https://github.com/TheSkyC/HistorySync/compare/v1.2.1...v1.2.2
[1.2.1]: https://github.com/TheSkyC/HistorySync/compare/v1.2.0...v1.2.1
[1.2.0]: https://github.com/TheSkyC/HistorySync/compare/v1.1.1...v1.2.0
[1.1.1]: https://github.com/TheSkyC/HistorySync/compare/v1.1.0...v1.1.1
[1.1.0]: https://github.com/TheSkyC/HistorySync/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/TheSkyC/HistorySync/commits/v1.0.0
