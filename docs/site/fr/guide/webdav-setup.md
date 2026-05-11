---
title: Configuration WebDAV
description: Configuration étape par étape pour la sauvegarde cloud WebDAV dans HistorySync — couvre Nextcloud, Synology, Alist, Nginx et plus encore.
---

# Configuration WebDAV

HistorySync utilise **WebDAV** pour sauvegarder et restaurer votre base de données d'historique de navigation vers et depuis le cloud. N'importe quel serveur compatible WebDAV fonctionne — cette page couvre les options les plus populaires.

---

## Fonctionnement

1. HistorySync **compresse** votre `history.db` (et éventuellement le cache de favicons).
2. Il téléverse l'archive vers le chemin WebDAV distant en utilisant un **flux atomique** — l'ancienne sauvegarde n'est remplacée qu'après le succès du téléversement.
3. Jusqu'à `max_backups` copies sont conservées ; les plus anciennes sont supprimées automatiquement.
4. Lors de la restauration, HistorySync télécharge la sauvegarde choisie et **fusionne** ses enregistrements avec votre base de données locale (ou la remplace en mode `--replace`).

---

## Configuration Rapide (Interface Graphique)

1. Ouvrez **Paramètres → Sauvegarde Cloud WebDAV**.
2. Remplissez les champs :
   - **URL** — URL complète incluant le chemin, ex. : `https://cloud.example.com/remote.php/dav/files/alice/`
   - **Nom d'utilisateur / Mot de passe** — vos identifiants WebDAV
   - **Chemin Distant** — sous-dossier pour les sauvegardes (par défaut : `HistorySync/`)
   - **Sauvegardes Max** — combien d'instantanés conserver (par défaut : 10)
3. Cliquez sur **Tester la connexion**.
4. Activez la **Sauvegarde automatique** et définissez un intervalle.

---

## Configuration Rapide (CLI)

```bash
hsync config set webdav.enabled true
hsync config set webdav.url "https://cloud.example.com/remote.php/dav/files/alice/"
hsync config set webdav.username "alice"

# Définissez le mot de passe dans l'interface graphique, ou pré-remplissez config.json.
# La commande hsync config n'expose pas actuellement la clé webdav.password.

hsync config set webdav.remote_path "HistorySync/"
hsync config set webdav.max_backups 7
hsync config set webdav.auto_backup true
hsync config set scheduler.auto_backup_enabled true
hsync config set scheduler.auto_backup_interval_hours 12

# Tester
hsync -b
```

---

## Guides par Fournisseur

### Nextcloud

Format d'URL WebDAV de Nextcloud :
```
https://<votre-domaine-nextcloud>/remote.php/dav/files/<nom-utilisateur>/
```

1. Connectez-vous à Nextcloud.
2. Allez dans **Paramètres → Sécurité → Appareils et sessions** et créez un **Mot de passe d'application** (recommandé plutôt que votre mot de passe principal).
3. Dans HistorySync, utilisez l'URL ci-dessus avec votre nom d'utilisateur Nextcloud et le mot de passe d'application.
4. Optionnel : créez d'abord un dossier dédié (ex. : `HistorySync`) et définissez `remote_path` à `HistorySync/`.

!!! tip "Mot de passe d'application Nextcloud"
    Utiliser un mot de passe d'application signifie que HistorySync ne peut accéder à rien d'autre dans votre compte si l'identifiant est compromis. Fortement recommandé.

---

### Synology DSM (QuickConnect / Direct)

**Activer WebDAV dans Synology DSM :**

1. Ouvrez **Panneau de configuration → Services de fichiers → WebDAV**.
2. Activez **WebDAV** ou **WebDAV HTTPS** (HTTPS est fortement recommandé).
3. Notez le port (par défaut : 5005 pour HTTP, 5006 pour HTTPS).

**Format d'URL HistorySync :**
```
https://<ip-synology-ou-quickconnect>:5006/
```

Définissez le chemin distant vers un dossier partagé auquel vous avez accès en écriture, ex. : `homes/alice/HistorySync/`.

!!! warning "Certificats auto-signés"
    Synology utilise un certificat auto-signé par défaut. Soit :
    - Installez un certificat Let's Encrypt dans DSM (recommandé), soit
    - Définissez `webdav.verify_ssl` à `false` (`hsync config set webdav.verify_ssl false`)

---

### AList (S3 / OneDrive / Google Drive via WebDAV)

[AList](https://alist.nn.ci/) est un gestionnaire de fichiers open-source qui expose de nombreux fournisseurs de stockage cloud en WebDAV.

```
https://<votre-domaine-alist>/dav/
```

Utilisez votre nom d'utilisateur et mot de passe AList. Définissez `remote_path` vers un chemin dans votre stockage configuré, ex. : `OneDrive/HistorySync/`.

---

### Nginx WebDAV

Si vous hébergez vous-même un serveur WebDAV Nginx :

```nginx
location /dav/ {
    root /var/webdav;
    dav_methods PUT DELETE MKCOL COPY MOVE;
    dav_ext_methods PROPFIND OPTIONS;
    dav_access user:rw group:rw all:r;
    create_full_put_path on;
    auth_basic "WebDAV";
    auth_basic_user_file /etc/nginx/.htpasswd;
}
```

URL HistorySync : `https://<votre-domaine>/dav/`

---

### Apache WebDAV

```apache
<Location /dav>
    DAV On
    AuthType Basic
    AuthName "WebDAV"
    AuthUserFile /etc/apache2/.htpasswd
    Require valid-user
</Location>
```

---

### Cloudflare R2 (via rclone)

R2 n'expose pas d'endpoint WebDAV natif, mais vous pouvez le proxy avec `rclone serve webdav` :

```bash
rclone serve webdav r2:my-bucket --addr :8080 --user alice --pass secret
```

Puis définissez `webdav.url` à `http://localhost:8080/`.

---

## Résolution des Problèmes

### "Connection refused" / "Timeout"

- Vérifiez l'URL — assurez-vous que le protocole (`https://`) et le port sont corrects.
- Vérifiez que le serveur est accessible depuis votre machine : `curl -u user:pass https://your-server/dav/`.

### "401 Unauthorized"

- Vérifiez à nouveau le nom d'utilisateur et le mot de passe.
- Pour Nextcloud : utilisez un **Mot de passe d'application**, pas votre mot de passe de connexion.
- Confirmez que le compte a la permission d'écriture sur le chemin distant.

### "SSL: CERTIFICATE_VERIFY_FAILED"

- Le serveur utilise un certificat auto-signé ou expiré.
- Soit corrigez le certificat, soit définissez `hsync config set webdav.verify_ssl false` (uniquement pour les réseaux internes de confiance).

### La sauvegarde réussit mais la restauration ne montre aucune sauvegarde

- Vérifiez `webdav.remote_path` — il doit correspondre au chemin utilisé lors de la sauvegarde.
- Exécutez `hsync restore --list` pour voir ce que `hsync` trouve sur le serveur.

### La grande sauvegarde prend trop de temps / expire

- HistorySync utilise des téléversements en flux continu, donc l'utilisation de la mémoire reste faible quelle que soit la taille du fichier.
- Si le serveur a un petit délai d'expiration de requête, augmentez-le (ex. : Nginx `client_body_timeout 300s;`).
- Envisagez d'exécuter les sauvegardes selon un planning (drapeau `-w` ou `scheduler.auto_backup_interval_hours`) plutôt que manuellement.

---

## Notes de Sécurité

- Les **identifiants WebDAV sont stockés chiffrés** sur le disque en utilisant des sous-clés dérivées HKDF. Voir [Architecture de Sécurité](../dev/security.md).
- Utilisez toujours **HTTPS** — le HTTP simple expose vos identifiants et les données d'historique en transit.
- Préférez les mots de passe spécifiques à l'application plutôt que votre mot de passe principal où le fournisseur le prend en charge.
- Définissez `max_backups` à un petit nombre si le stockage est limité. La valeur par défaut est **5**.
