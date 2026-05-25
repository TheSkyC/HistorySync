---
title: Security Architecture
description: How HistorySync protects sensitive data — HKDF key derivation, HKDF-SHA256 keystream XOR encryption, OS keychain storage, and threat model.
---

# Security Architecture

HistorySync handles sensitive data — browsing history and WebDAV credentials. This page explains exactly how that data is protected.

---

## Threat Model

HistorySync is designed to protect against:

- **Credential theft** — a malicious process reading the config file on disk should not be able to recover plain-text WebDAV passwords.
- **In-transit data exposure** — history backups and restores must use encrypted connections.
- **Accidental data loss** — corrupted configs and failed uploads must not leave the database in an inconsistent state.

HistorySync does **not** protect against:

- A compromised OS or root-level attacker (who can access the keychain directly).
- Physical access attacks (full-disk encryption is outside the scope of this application).
- An attacker who can execute code in the same user session.

---

## Security Architecture V2

### Master Key Storage

A cryptographically random **256-bit master key** is generated on first run and stored in the **OS keychain** using the [`keyring`](https://github.com/jaraco/keyring) library:

| Platform | Keychain backend |
|---|---|
| Windows | Windows Credential Manager |
| macOS | macOS Keychain |
| Linux | Secret Service API (GNOME Keyring, KWallet, etc.) |

The master key never touches the disk directly. All disk-persisted data uses **derived subkeys**.

---

### Key Derivation (HKDF)

From the master key, HistorySync derives **independent subkeys** for each purpose using [HKDF](https://en.wikipedia.org/wiki/HKDF) (HMAC-based Key Derivation Function):

```
Master Key (256 bits)
    │
    ├── HKDF(info="encryption") → Encryption Subkey (256 bits)
    └── HKDF(info="authentication") → Authentication Subkey (256 bits)
```

Using independent subkeys means that compromising one subkey (e.g. via a cryptanalytic attack on the encryption algorithm) does not compromise the other.

---

### Encryption of Sensitive Values

WebDAV passwords and other sensitive config values are encrypted using **HKDF-SHA256 keystream XOR** authenticated with **HMAC-SHA256**:

```
encrypt(plaintext, master_key):
    salt       ← random 16-byte salt
    prk        ← HMAC-SHA256(key=salt, data=master_key)          # HKDF-Extract
    enc_key    ← HKDF-Expand(prk, info="historysync-enc-key")
    auth_key   ← HKDF-Expand(prk, info="historysync-auth-key")
    keystream  ← HKDF-Expand(prk, info="historysync-enc-key", length=len(padded_plaintext))
    ciphertext ← padded_plaintext XOR keystream
    tag        ← HMAC-SHA256(key=auth_key, data=salt ‖ ciphertext)
    return base64(0x02 ‖ salt ‖ tag ‖ ciphertext)
```

The result is stored as a Base64 string in `config.json`. On load, the HMAC tag is verified before decryption is attempted.

HMAC-SHA256 provides **authenticated encryption** — any tampering with the ciphertext causes HMAC verification to fail with a `DecryptionError`, which is caught and logged. The app continues with an empty password rather than crashing or silently accepting a corrupt value.

---

### Config File Safety

The config file (`config.json`) is written using **atomic rename**:

1. Data is written to a temporary file in the same directory.
2. `fsync()` is called to flush to disk.
3. The temporary file is **renamed** over the existing config file.

This ensures the config is never in a partially-written state. If the process is killed mid-write, the old config is preserved intact.

If the config file is found to be corrupt on load, it is:
1. Backed up to `config.json.bak`.
2. Replaced with a fresh default config.
3. The user is shown a warning dialog.

---

### WebDAV Transport Security

- All WebDAV connections use **HTTPS** by default.
- SSL certificate verification is **enabled by default** (`webdav.verify_ssl = true`).
- Disabling SSL verification (`verify_ssl = false`) is possible for self-signed certs on trusted internal networks, but is **not recommended** for internet-facing servers.
- Backup uploads use **atomic streaming** — the remote file is only replaced after the upload completes successfully.

---

## Password / Master Password (GUI Lock)

HistorySync supports an optional **master password** that locks the GUI. This is separate from the WebDAV credential encryption above.

- The password is stored as a **bcrypt hash** in `config.json` (the `master_password_hash` field).
- The bcrypt hash is one-way — even if `config.json` is stolen, the plain-text password cannot be recovered.
- The master password does **not** encrypt the history database itself — it only locks the GUI.

---

## Privacy Features

| Feature | Description |
|---|---|
| **Domain Blacklist** | Domains on the blacklist are never imported, and existing records are permanently deleted. |
| **URL Prefix Filters** | Internal browser URLs (`chrome://`, `about:`, `file://`, etc.) are filtered by default. |
| **Soft-Hide** | Records can be hidden from the main view without deletion. |
| **Hidden Records View** | A separate, access-controlled view for soft-hidden records. |
| **Headless / Fresh Mode** | `--fresh` mode uses a temporary directory — no reads or writes to the real config/database. Useful for privacy-sensitive demos or troubleshooting. |

---

## Reporting Vulnerabilities

**Do not open a public GitHub issue for security vulnerabilities.**

Please email **security@historysync.app** with:

- A description of the vulnerability.
- Steps to reproduce.
- Potential impact.

You will receive a response within **72 hours**. We will coordinate a fix and responsible disclosure timeline with you.
