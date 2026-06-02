---
title: FAQ
description: Questions fréquemment posées sur HistorySync — installation, synchronisation, confidentialité, WebDAV et plus encore.
---

# Questions Fréquemment Posées

---

## Général

### HistorySync téléverse-t-il mes données de navigation vers un tiers ?

**Non.** HistorySync est entièrement axé sur le stockage local. Toutes les données d'historique sont stockées dans une base de données SQLite **sur votre propre machine**. Le seul trafic réseau est la sauvegarde WebDAV optionnelle — qui va vers un serveur *que vous* contrôlez (ou un service auto-hébergé). Aucune analyse, télémétrie ou appel externe n'est jamais effectué.

### Quels navigateurs sont pris en charge ?

HistorySync prend en charge nativement **30+ navigateurs**, notamment :

**Basés sur Chromium :** Chrome, Edge, Brave, Vivaldi, Arc, Chromium, Opera, Opera GX, Yandex Browser, CentBrowser, Thorium et bien d'autres.

**Basés sur Firefox :** Firefox, Firefox ESR, LibreWolf, Waterfox, Pale Moon, SeaMonkey, Basilisk.

**Safari :** macOS uniquement.

**Navigateurs régionaux (Windows/macOS/Linux) :** QQ Browser, Sogou, UC Browser, Liebao, Maxthon, Twinkstar et d'autres.

Si votre navigateur n'est pas listé, utilisez **Paramètres → Navigateurs → Ajouter un chemin personnalisé** pour l'ajouter manuellement, ou essayez la fonctionnalité de détection intelligente.

### Puis-je utiliser HistorySync sur plusieurs ordinateurs ?

Oui ! Installez HistorySync sur chaque machine, configurez le même serveur WebDAV sur toutes, et activez la synchronisation automatique. Lorsque vous restaurez (ou lorsque HistorySync fusionne automatiquement depuis le cloud), les enregistrements de tous les appareils sont **dédupliqués intelligemment** en fonction du type de navigateur, de l'URL et de l'horodatage de visite.

### Puis-je ajouter des navigateurs que HistorySync ne détecte pas automatiquement ?

Oui. Utilisez **Paramètres → Navigateurs → Ajouter un chemin personnalisé** pour enregistrer manuellement un navigateur. À partir de la version 1.4.0, les navigateurs personnalisés utilisent le même modèle d'exécution que les navigateurs intégrés et ceux détectés par analyse approfondie, donc ils participent à la synchronisation, au suivi d'état et aux commandes d'activation/désactivation sans nécessiter de redémarrage après l'enregistrement.

---

## Synchronisation et Extraction

### HistorySync fonctionne-t-il pendant que mon navigateur est ouvert ?

Oui. HistorySync utilise des **instantanés WAL (Write-Ahead Log) SQLite** — il copie le fichier WAL avant de lire, donc il n'y a jamais de conflit avec un navigateur en cours d'exécution. Votre navigateur n'est jamais verrouillé ni mis en pause.

### Pourquoi certains enregistrements manquent-ils après une synchronisation ?

Plusieurs raisons possibles :

- **Navigation privée/incognito** — les navigateurs n'écrivent pas l'historique incognito sur le disque ; HistorySync ne peut pas le voir.
- **Profil de navigateur désactivé** — vérifiez **Paramètres → Navigateurs** et confirmez que le profil n'est pas désactivé.
- **URL filtrée** — HistorySync ignore les URLs internes des navigateurs (`chrome://`, `about:`, `file://`, etc.) et tout domaine figurant sur votre liste noire.
- **La première synchronisation était incrémentielle** — essayez **Paramètres → Maintenance → Resynchronisation complète**, ou utilisez le point d'entrée de démarrage GUI `python -m src.main --resync`, pour relire tout l'historique.

### Qu'est-ce qu'une « resynchronisation complète » ?

Une synchronisation normale est **incrémentielle** — elle ne lit que les enregistrements plus récents que le dernier horodatage de synchronisation. Une resynchronisation complète ignore le repère et relit chaque enregistrement de chaque navigateur, en remplissant les champs comme `visit_count` qui ont pu changer. Il est sûr de l'exécuter à tout moment — les enregistrements sont mis à jour par insertion, pas dupliqués.

```bash
# Point d'entrée de démarrage GUI (pas le CLI hsync)
python -m src.main --resync

# Depuis l'interface graphique : Paramètres → Maintenance → Resynchronisation complète
```

---

## Confidentialité et Sécurité

### Où sont stockées mes données ?

| Plateforme | Emplacement par défaut |
|---|---|
| Windows | `%APPDATA%\HistorySync\` |
| macOS | `~/Library/Application Support/HistorySync/` |
| Linux | `~/.config/HistorySync/` |

Utilisez `--config-dir CHEMIN` pour remplacer, ou `--portable` pour stocker tout à côté de l'exécutable.

### Comment les identifiants WebDAV sont-ils protégés ?

Les identifiants ne sont **jamais stockés en texte clair**. HistorySync dérive des sous-clés indépendantes de chiffrement et d'authentification depuis une clé maîtresse stockée dans le trousseau de clés du système d'exploitation (via `keyring`), en utilisant HKDF. Voir [Architecture de Sécurité](../dev/security.md) pour les détails complets.

### Qu'est-ce que le « masquage discret » / les enregistrements masqués ?

Le masquage discret marque un enregistrement (ou tous les enregistrements d'un domaine) comme masqué — ils disparaissent de la vue principale Historique mais restent dans la base de données. Vous pouvez les voir dans **Historique → Afficher les masqués**. C'est utile pour masquer des pages sensibles sans les supprimer définitivement.

### Qu'est-ce que la liste noire de domaines ?

Les domaines sur la liste noire ne sont **jamais importés**, et tous les enregistrements existants pour ces domaines sont **définitivement supprimés**. Clic droit sur un enregistrement → **Mettre le domaine en liste noire**, ou gérez la liste dans **Paramètres → Confidentialité → Liste noire de domaines**.

---

## WebDAV et Sauvegarde Cloud

### Quels fournisseurs WebDAV fonctionnent avec HistorySync ?

N'importe quel serveur WebDAV standard. Testé avec : Nextcloud, Synology DSM, ownCloud, AList, Nginx WebDAV, Apache mod_dav, Caddy WebDAV. Voir le [guide de configuration WebDAV](webdav-setup.md) pour les instructions spécifiques à chaque fournisseur.

### Combien de sauvegardes sont conservées ?

Par défaut, **10 sauvegardes** sont conservées sur le serveur. Les plus anciennes sont supprimées automatiquement après chaque téléversement réussi. Modifiez cela avec `hsync config set webdav.max_backups N`.

### La sauvegarde a échoué avec « Connection refused » — que dois-je vérifier ?

1. Vérifiez l'URL WebDAV (protocole, nom d'hôte, port, chemin).
2. Vérifiez le nom d'utilisateur et le mot de passe — pour Nextcloud, utilisez un **Mot de passe d'application**.
3. Testez la connectivité : `curl -u user:pass https://your-server/dav/`.
4. Si vous utilisez un certificat auto-signé, définissez `hsync config set webdav.verify_ssl false`.

### Comment fonctionne le nouveau système de mise à jour selon le type d'installation ?

HistorySync détecte si vous utilisez une version installée, portable, AppImage, `.dmg` ou un paquet géré par le système.

- Les builds de type installateur peuvent généralement déléguer directement au programme d'installation de la plateforme.
- Les installations portables, AppImage et par archive téléchargent le bon artefact et le révèlent pour un remplacement manuel sûr.
- Les installations via gestionnaire de paquets, comme les paquets `.deb`, continuent d'utiliser le gestionnaire de paquets au lieu de remplacer les fichiers sur place.

Vous pouvez toujours lancer une vérification manuelle dans **Paramètres → Mises à jour**, ou exécuter `hsync update` depuis le terminal.

---

## Performances

### HistorySync est lent avec des millions d'enregistrements — que puis-je faire ?

Essayez ces étapes dans l'ordre :

1. **Exécutez `hsync db vacuum`** — récupère l'espace fragmenté et actualise les statistiques du planificateur de requêtes.
2. **Exécutez `hsync db rebuild-fts`** — reconstruit l'index de recherche en texte intégral.
3. Assurez-vous que votre base de données est sur un SSD local rapide, pas sur un partage réseau ou un lecteur USB.
4. Si vous utilisez une recherche par expression régulière, envisagez de passer à une recherche par mot-clé simple — la regex est plus rapide via SQL pushdown, mais les modèles très complexes peuvent quand même être lents.

### Combien d'espace disque la base de données utilise-t-elle ?

Cela dépend du nombre d'enregistrements et de la quantité de métadonnées de page stockées. Un guide approximatif :

| Enregistrements | Taille approximative |
|---|---|
| 100 000 | ~20–40 Mo |
| 500 000 | ~80–150 Mo |
| 1 000 000 | ~150–300 Mo |
| 5 000 000 | ~600 Mo – 1,2 Go |

Exécutez `hsync db vacuum` périodiquement pour garder le fichier compact.

---

## CLI (`hsync`)

### Comment installer `hsync` comme commande système ?

Si vous exécutez depuis les sources :
```bash
# Linux / macOS
echo '#!/bin/sh\npython -m src.cli "$@"' > /usr/local/bin/hsync
chmod +x /usr/local/bin/hsync
```

Si vous utilisez le paquet pré-compilé, l'installateur place généralement `hsync` dans votre `PATH` automatiquement.

### Puis-je utiliser `hsync` dans un conteneur Docker / pipeline CI ?

Oui. Utilisez le mode `--headless` pour éviter toute dépendance GUI :

```bash
python -m src.main --headless --sync --config-dir /data/config
```

Ou utilisez `hsync` directement :

```bash
hsync -s --config-dir /data/config -q
```

Définissez `QT_QPA_PLATFORM=offscreen` si Qt se plaint d'un affichage manquant.

### Puis-je vérifier les nouvelles versions depuis des scripts ?

Oui. Utilisez :

```bash
hsync update --json
```

Cela renvoie des métadonnées structurées adaptées à l'automatisation. Vous pouvez aussi remplacer le canal par invocation avec `--channel beta` ou `--channel nightly`.

---

## Contribution et Développement

### Comment signaler un bug ?

Utilisez le **[modèle de rapport de bug GitHub](https://github.com/TheSkyC/HistorySync/issues/new?template=bug_report.yml)**. Incluez votre OS, la version de HistorySync, les navigateurs concernés et les étapes pour reproduire.

### J'ai trouvé une faille de sécurité — que dois-je faire ?

**N'ouvrez pas de problème public.** Envoyez un e-mail directement au mainteneur à **security@historysync.app** avec une description, les étapes de reproduction et l'impact potentiel. Vous recevrez une réponse dans les 72 heures.

### Comment ajouter la prise en charge d'un nouveau navigateur ?

Voir le [guide de contribution](../dev/contributing.md). Les extracteurs de navigateurs se trouvent dans `src/services/extractors/`. La plupart des nouveaux forks Chromium peuvent être ajoutés avec seulement quelques lignes en sous-classant `ChromiumExtractor`.
