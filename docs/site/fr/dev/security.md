---
title: Architecture de Sécurité
description: Comment HistorySync protège les données sensibles — dérivation de clés HKDF, chiffrement XOR par flux de clés HKDF-SHA256, stockage dans le trousseau de clés du système d'exploitation et modèle de menace.
---

# Architecture de Sécurité

HistorySync gère des données sensibles — l'historique de navigation et les identifiants WebDAV. Cette page explique exactement comment ces données sont protégées.

---

## Modèle de Menace

HistorySync est conçu pour se protéger contre :

- **Vol d'identifiants** — un processus malveillant lisant le fichier de configuration sur le disque ne devrait pas pouvoir récupérer les mots de passe WebDAV en texte clair.
- **Exposition des données en transit** — les sauvegardes et restaurations d'historique doivent utiliser des connexions chiffrées.
- **Perte accidentelle de données** — les configurations corrompues et les téléversements échoués ne doivent pas laisser la base de données dans un état incohérent.

HistorySync ne protège **pas** contre :

- Un système d'exploitation compromis ou un attaquant au niveau root (qui peut accéder directement au trousseau de clés).
- Les attaques d'accès physique (le chiffrement complet du disque dépasse le cadre de cette application).
- Un attaquant pouvant exécuter du code dans la même session utilisateur.

---

## Architecture de Sécurité V2

### Stockage de la Clé Maîtresse

Une **clé maîtresse de 256 bits** cryptographiquement aléatoire est générée au premier lancement et stockée dans le **trousseau de clés du système d'exploitation** en utilisant la bibliothèque [`keyring`](https://github.com/jaraco/keyring) :

| Plateforme | Backend du trousseau |
|---|---|
| Windows | Gestionnaire des informations d'identification Windows |
| macOS | Trousseau macOS |
| Linux | API Secret Service (GNOME Keyring, KWallet, etc.) |

La clé maîtresse ne touche jamais directement le disque. Toutes les données persistées sur disque utilisent des **sous-clés dérivées**.

---

### Dérivation de Clés (HKDF)

Depuis la clé maîtresse, HistorySync dérive des **sous-clés indépendantes** pour chaque usage en utilisant [HKDF](https://fr.wikipedia.org/wiki/HKDF) (Fonction de Dérivation de Clés basée sur HMAC) :

```
Clé Maîtresse (256 bits)
    │
    ├── HKDF(info="encryption") → Sous-clé de Chiffrement (256 bits)
    └── HKDF(info="authentication") → Sous-clé d'Authentification (256 bits)
```

L'utilisation de sous-clés indépendantes signifie que compromettre une sous-clé (par exemple via une attaque cryptanalytique sur l'algorithme de chiffrement) ne compromet pas l'autre.

---

### Chiffrement des Valeurs Sensibles

Les mots de passe WebDAV et autres valeurs de configuration sensibles sont chiffrés en utilisant **XOR par flux de clés HKDF-SHA256** authentifié avec **HMAC-SHA256** :

```
encrypt(plaintext, master_key):
    salt       ← sel aléatoire de 16 octets
    prk        ← HMAC-SHA256(key=salt, data=master_key)          # HKDF-Extract
    enc_key    ← HKDF-Expand(prk, info="historysync-enc-key")
    auth_key   ← HKDF-Expand(prk, info="historysync-auth-key")
    keystream  ← HKDF-Expand(prk, info="historysync-enc-key", length=len(padded_plaintext))
    ciphertext ← padded_plaintext XOR keystream
    tag        ← HMAC-SHA256(key=auth_key, data=salt ‖ ciphertext)
    return base64(0x02 ‖ salt ‖ tag ‖ ciphertext)
```

Le résultat est stocké comme chaîne Base64 dans `config.json`. Au chargement, le tag HMAC est vérifié avant toute tentative de déchiffrement.

HMAC-SHA256 fournit un **chiffrement authentifié** — toute altération du texte chiffré provoque l'échec de la vérification HMAC avec une `DecryptionError`, qui est capturée et journalisée. L'application continue avec un mot de passe vide plutôt que de planter ou d'accepter silencieusement une valeur corrompue.

---

### Sécurité du Fichier de Configuration

Le fichier de configuration (`config.json`) est écrit en utilisant un **renommage atomique** :

1. Les données sont écrites dans un fichier temporaire dans le même répertoire.
2. `fsync()` est appelé pour vider sur le disque.
3. Le fichier temporaire est **renommé** par-dessus le fichier de configuration existant.

Cela garantit que la configuration n'est jamais dans un état partiellement écrit. Si le processus est tué en milieu d'écriture, l'ancienne configuration est préservée intacte.

Si le fichier de configuration est trouvé corrompu au chargement, il est :
1. Sauvegardé vers `config.json.bak`.
2. Remplacé par une configuration fraîche par défaut.
3. L'utilisateur reçoit une boîte de dialogue d'avertissement.

---

### Sécurité du Transport WebDAV

- Toutes les connexions WebDAV utilisent **HTTPS** par défaut.
- La vérification du certificat SSL est **activée par défaut** (`webdav.verify_ssl = true`).
- Désactiver la vérification SSL (`verify_ssl = false`) est possible pour les certificats auto-signés sur des réseaux internes de confiance, mais n'est **pas recommandé** pour les serveurs exposés sur Internet.
- Les téléversements de sauvegarde utilisent un **flux atomique** — le fichier distant n'est remplacé qu'après la complétion réussie du téléversement.

---

## Mot de Passe / Mot de Passe Maître (Verrouillage GUI)

HistorySync prend en charge un **mot de passe maître** optionnel qui verrouille l'interface graphique. Ceci est distinct du chiffrement des identifiants WebDAV décrit ci-dessus.

- Le mot de passe est stocké comme un **hash bcrypt** dans `config.json` (le champ `master_password_hash`).
- Le hash bcrypt est unidirectionnel — même si `config.json` est volé, le mot de passe en texte clair ne peut pas être récupéré.
- Le mot de passe maître ne **chiffre pas** la base de données d'historique elle-même — il verrouille uniquement l'interface graphique.

---

## Fonctionnalités de Confidentialité

| Fonctionnalité | Description |
|---|---|
| **Liste noire de domaines** | Les domaines sur la liste noire ne sont jamais importés, et les enregistrements existants sont définitivement supprimés. |
| **Filtres de préfixes d'URL** | Les URLs internes des navigateurs (`chrome://`, `about:`, `file://`, etc.) sont filtrées par défaut. |
| **Masquage discret** | Les enregistrements peuvent être masqués de la vue principale sans suppression. |
| **Vue des enregistrements masqués** | Une vue séparée avec contrôle d'accès pour les enregistrements masqués discrètement. |
| **Mode sans interface / Fresh** | Le mode `--fresh` utilise un répertoire temporaire — aucune lecture ni écriture vers la configuration/base de données réelle. Utile pour les démos sensibles à la confidentialité ou le dépannage. |

---

## Signalement des Failles

**N'ouvrez pas de problème public GitHub pour les failles de sécurité.**

Veuillez envoyer un e-mail à **security@historysync.app** avec :

- Une description de la faille.
- Les étapes pour reproduire.
- L'impact potentiel.

Vous recevrez une réponse dans les **72 heures**. Nous coordonnerons avec vous un calendrier de correction et de divulgation responsable.
