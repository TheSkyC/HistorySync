---
title: Настройка WebDAV
description: Пошаговая настройка облачного резервного копирования WebDAV в HistorySync — Nextcloud, Synology, Alist, Nginx и другие.
---

# Настройка WebDAV

HistorySync использует **WebDAV** для резервного копирования и восстановления базы данных истории браузера в облако и из него. Подходит любой WebDAV-совместимый сервер — на этой странице рассматриваются наиболее популярные варианты.

---

## Принцип Работы

1. HistorySync **архивирует** ваш `history.db` (и при необходимости кэш иконок).
2. Он загружает архив на удалённый WebDAV-путь, используя **атомарную потоковую передачу** — старая резервная копия заменяется только после успешной загрузки.
3. Хранится до `max_backups` копий; более старые удаляются автоматически.
4. При восстановлении HistorySync скачивает выбранную резервную копию и **объединяет** её записи с локальной базой данных (или заменяет её в режиме `--replace`).

---

## Быстрая Настройка (GUI)

1. Откройте **Настройки → Облачное резервное копирование WebDAV**.
2. Заполните поля:
   - **URL** — полный URL, включая путь, например: `https://cloud.example.com/remote.php/dav/files/alice/`
   - **Имя пользователя / Пароль** — ваши учётные данные WebDAV
   - **Удалённый путь** — подпапка для резервных копий (по умолчанию: `HistorySync/`)
   - **Макс. резервных копий** — сколько снимков хранить (по умолчанию: 10)
3. Нажмите **Проверить соединение**.
4. Включите **Автоматическое резервное копирование** и установите интервал.

---

## Быстрая Настройка (CLI)

```bash
hsync config set webdav.enabled true
hsync config set webdav.url "https://cloud.example.com/remote.php/dav/files/alice/"
hsync config set webdav.username "alice"

# Пароль задавайте через GUI или предварительно подставляйте в config.json.
# Команда hsync config сейчас не поддерживает ключ webdav.password.

hsync config set webdav.remote_path "HistorySync/"
hsync config set webdav.max_backups 7
hsync config set webdav.auto_backup true
hsync config set scheduler.auto_backup_enabled true
hsync config set scheduler.auto_backup_interval_hours 12

# Проверить
hsync -b
```

---

## Руководства по Провайдерам

### Nextcloud

Формат WebDAV URL для Nextcloud:
```
https://<ваш-домен-nextcloud>/remote.php/dav/files/<имя-пользователя>/
```

1. Войдите в Nextcloud.
2. Перейдите в **Настройки → Безопасность → Устройства и сессии** и создайте **Пароль приложения** (рекомендуется вместо основного пароля).
3. В HistorySync используйте URL выше с вашим именем пользователя Nextcloud и паролем приложения.
4. Необязательно: сначала создайте отдельную папку (например, `HistorySync`) и установите `remote_path` в `HistorySync/`.

!!! tip "Пароль приложения Nextcloud"
    Использование пароля приложения означает, что HistorySync не сможет получить доступ к другим данным вашего аккаунта при утечке учётных данных. Настоятельно рекомендуется.

---

### Synology DSM (QuickConnect / Прямое подключение)

**Включение WebDAV в Synology DSM:**

1. Откройте **Панель управления → Службы файлов → WebDAV**.
2. Включите **WebDAV** или **WebDAV HTTPS** (HTTPS настоятельно рекомендуется).
3. Запомните порт (по умолчанию: 5005 для HTTP, 5006 для HTTPS).

**Формат URL для HistorySync:**
```
https://<ip-synology-или-quickconnect>:5006/
```

Установите удалённый путь в общую папку, к которой у вас есть права записи, например: `homes/alice/HistorySync/`.

!!! warning "Самоподписанные сертификаты"
    Synology использует самоподписанный сертификат по умолчанию. Либо:
    - Установите сертификат Let's Encrypt в DSM (рекомендуется), либо
    - Установите `webdav.verify_ssl` в `false` (`hsync config set webdav.verify_ssl false`)

---

### AList (S3 / OneDrive / Google Drive через WebDAV)

[AList](https://alist.nn.ci/) — это менеджер файлов с открытым исходным кодом, который предоставляет доступ ко многим облачным хранилищам через WebDAV.

```
https://<ваш-домен-alist>/dav/
```

Используйте имя пользователя и пароль AList. Установите `remote_path` в путь внутри настроенного хранилища, например: `OneDrive/HistorySync/`.

---

### Nginx WebDAV

Если вы самостоятельно хостите WebDAV-сервер Nginx:

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

URL HistorySync: `https://<ваш-домен>/dav/`

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

### Cloudflare R2 (через rclone)

R2 не предоставляет нативной конечной точки WebDAV, но вы можете проксировать его через `rclone serve webdav`:

```bash
rclone serve webdav r2:my-bucket --addr :8080 --user alice --pass secret
```

Затем установите `webdav.url` в `http://localhost:8080/`.

---

## Устранение Неполадок

### «Connection refused» / «Timeout»

- Проверьте URL — убедитесь, что протокол (`https://`) и порт указаны правильно.
- Проверьте доступность сервера с вашей машины: `curl -u user:pass https://your-server/dav/`.

### «401 Unauthorized»

- Перепроверьте имя пользователя и пароль.
- Для Nextcloud: используйте **Пароль приложения**, а не основной пароль.
- Убедитесь, что у аккаунта есть права записи на удалённый путь.

### «SSL: CERTIFICATE_VERIFY_FAILED»

- Сервер использует самоподписанный или истёкший сертификат.
- Либо исправьте сертификат, либо выполните `hsync config set webdav.verify_ssl false` (только для доверенных внутренних сетей).

### Резервное копирование успешно, но восстановление не показывает копии

- Проверьте `webdav.remote_path` — он должен совпадать с путём, использованным при резервном копировании.
- Выполните `hsync restore --list`, чтобы увидеть, что `hsync` находит на сервере.

### Большая резервная копия занимает слишком много времени / истекает время ожидания

- HistorySync использует потоковую загрузку, поэтому использование памяти остаётся низким независимо от размера файла.
- Если у сервера небольшой таймаут запроса, увеличьте его (например, Nginx `client_body_timeout 300s;`).
- Рассмотрите возможность запуска резервного копирования по расписанию (флаг `-w` или `scheduler.auto_backup_interval_hours`) вместо ручного запуска.

---

## Примечания по Безопасности

- **Учётные данные WebDAV хранятся в зашифрованном виде** на диске с использованием подключей, производных HKDF. См. [Архитектура Безопасности](../dev/security.md).
- Всегда используйте **HTTPS** — обычный HTTP раскрывает ваши учётные данные и данные истории при передаче.
- По возможности предпочитайте пароли приложений основному паролю аккаунта.
- Установите `max_backups` на небольшое значение, если место для хранения ограничено. По умолчанию **5**.
