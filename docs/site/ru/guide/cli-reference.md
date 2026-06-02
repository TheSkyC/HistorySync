---
title: Справочник CLI
description: Полный справочник по инструменту командной строки hsync — все флаги, подкоманды и расширенный DSL запросов.
---

# Справочник CLI — `hsync`

`hsync` — это **CLI без графического интерфейса** для HistorySync. Он предоставляет все возможности приложения без GUI, что делает его идеальным для запланированных задач, скриптов и CI-сред.

---

## Глобальные Параметры

Эти параметры доступны для каждой команды и подкоманды.

| Флаг | Краткий | Описание |
|---|---|---|
| `--version` | | Вывести версию и выйти |
| `--config-dir PATH` | | Использовать пользовательскую директорию конфигурации/данных |
| `--portable` | | Хранить все данные рядом с бинарным файлом `hsync` |
| `--verbose` | `-v` | Включить журналирование на уровне отладки |
| `--quiet` | `-q` | Подавить вывод прогресса; выводить только ошибки в stderr |
| `--no-color` | | Отключить цвета ANSI (также через переменную среды `NO_COLOR`) |
| `--dry-run` | | Обнаружить/проверить без записи чего-либо |

---

## Классические Флаги Действий

Быстрые однократные действия через флаги (подкоманда не требуется).

### `-s` / `--sync` — Извлечение Истории Браузера

Импортировать историю браузера в локальную базу данных.

```bash
hsync -s
hsync --sync

# Синхронизировать только конкретные браузеры
hsync -s --browsers chrome,firefox

# Синхронизировать каждые 30 минут (режим наблюдения)
hsync -s -w 30
```

**Параметры синхронизации:**

| Флаг | Описание |
|---|---|
| `--browsers LIST` | Типы браузеров через запятую (по умолчанию: все обнаруженные). Например: `chrome,firefox,edge` |
| `-w MINUTES` / `--watch MINUTES` | Повторять синхронизацию каждые `MINUTES` минут. Нажмите <kbd>Ctrl</kbd>+<kbd>C</kbd> для остановки. |

### `-b` / `--backup` — Резервное Копирование WebDAV

Загрузить сжатый снимок локальной базы данных на WebDAV.

```bash
hsync -b
hsync --backup

# Синхронизировать и создать резервную копию за один раз
hsync -sb
```

!!! note "WebDAV должен быть настроен заранее"
    Выполните `hsync config set webdav.enabled true` и задайте URL, имя пользователя и пароль перед использованием `--backup`.

<a id="export"></a>

### `-e ФАЙЛ` / `--export ФАЙЛ` — Экспорт Истории

Экспортировать историю браузера в файл. Формат определяется по расширению файла.

```bash
# Базовый экспорт в CSV
hsync -e history.csv

# Экспорт в JSON с фильтрами
hsync -e history.json --keyword python --after 2024-01-01

# HTML-отчёт со встроенными иконками
hsync -e report.html --format html --embed-icons

# Фильтрация по домену(-ам)
hsync -e out.csv --domain github.com --domain stackoverflow.com

# Пользовательские столбцы
hsync -e out.csv --columns title,url,visit_time,browser_type

# Фильтр по регулярному выражению
hsync -e out.json --keyword "^https://github" --regex

# Диапазон дат
hsync -e out.csv --after 2024-01-01 --before 2024-12-31
```

**Параметры экспорта:**

| Флаг | Описание |
|---|---|
| `--format FMT` | `csv` \| `json` \| `html` (по умолчанию: определяется по расширению) |
| `--columns COLS` | Столбцы через запятую. Доступны: `id`, `title`, `url`, `visit_time`, `visit_count`, `browser_type`, `profile_name`, `domain`, `metadata`, `typed_count`, `first_visit_time`, `transition_type`, `visit_duration` |
| `--embed-icons` | Встроить иконки как Base64 URI данных (только для HTML-экспорта) |
| `--keyword TEXT` | Полнотекстовый фильтр по ключевому слову |
| `--regex` | Обрабатывать `--keyword` как регулярное выражение Python |
| `--browser TYPE` | Фильтр по типу браузера (например: `chrome`, `firefox`, `edge`) |
| `--after DATE` | Включать записи начиная с `ГГГГ-ММ-ДД` (включительно) |
| `--before DATE` | Включать записи до `ГГГГ-ММ-ДД` (включительно) |
| `--domain HOST` | Фильтр по домену. Повторяемый: `--domain a.com --domain b.com` |

### `-S` / `--status` — Статистика Базы Данных

Вывести статистику базы данных.

```bash
hsync -S
hsync --status

# Машиночитаемый JSON
hsync -S --json

# Краткая строка (для скриптов)
hsync -S -q
```

**Пример вывода:**
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

### `-i` / `--interactive` — Интерактивное Меню

Запустить интерактивное меню в терминале — отлично подходит для первого использования.

```bash
hsync -i
hsync --interactive
```

---

## Подкоманды

### `search` — Поиск в Истории

Поиск в записях истории с использованием структурированного синтаксиса запросов.

```bash
# Просмотр последних 20 записей
hsync search

# Просмотр последних 100
hsync search --limit 100

# Простой поиск по ключевому слову
hsync search python

# Интерактивный режим с навигацией с клавиатуры
hsync search -i

# Структурированные запросы
hsync search "domain:github.com python"
hsync search "after:2024-01-01 browser:chrome" --limit 50
hsync search "is:bookmarked tag:work" --format json
hsync search "react -tutorial" --open
```

**Параметры:**

| Флаг | По умолч. | Описание |
|---|---|---|
| `--limit N` | `20` | Максимальное количество результатов |
| `--format FMT` | `table` | Формат вывода: `table` \| `json` \| `tsv` \| `csv` |
| `--columns COLS` | `title,url,visit_time,browser_type` | Столбцы для отображения |
| `--open` | | Открыть URL первого результата в браузере по умолчанию |
| `-i` / `--interactive` | | Интерактивный режим навигации с клавиатуры |

---

<a id="query-dsl"></a>

### DSL Запросов

Подкоманда поиска и строка поиска в GUI поддерживают богатый язык запросов.

#### Поиск по Ключевым Словам

Обычные слова ищут по заголовкам и URL:
```
python async
"точная фраза"
react -tutorial         # исключить термин
```

#### Токены-Фильтры

| Токен | Пример | Описание |
|---|---|---|
| `domain:` | `domain:github.com` | Фильтр по домену |
| `title:` | `title:python` | Поиск только в заголовке страницы |
| `url:` | `url:github` | Поиск только в URL |
| `after:` | `after:2024-01-01` | Начало диапазона дат (включительно) |
| `before:` | `before:2024-12-31` | Конец диапазона дат (включительно) |
| `browser:` | `browser:chrome` | Фильтр по типу браузера |
| `device:` | `device:laptop` | Фильтр по имени или UUID устройства |
| `is:bookmarked` | `is:bookmarked` | Только записи в закладках |
| `has:note` | `has:note` | Только записи с аннотациями |
| `tag:` | `tag:work` | Фильтр закладок по тегу |

#### Комбинирование Токенов

Токены и ключевые слова можно свободно комбинировать:
```
domain:arxiv.org after:2024-01-01 deep learning
is:bookmarked tag:work project management
browser:firefox -youtube after:2025-01-01
```

---

### `restore` — Восстановление из WebDAV

Восстановить базу данных из резервной копии WebDAV.

```bash
# Список резервных копий и интерактивный выбор
hsync restore

# Автоматически восстановить последнюю резервную копию (слияние)
hsync restore --latest

# Список доступных резервных копий в JSON
hsync restore --list

# Режим замены: полностью перезаписать локальную базу данных
hsync restore --replace

# Также восстановить кэш иконок
hsync restore --latest --restore-favicons
```

**Параметры:**

| Флаг | Описание |
|---|---|
| `--latest` | Автоматически использовать последнюю резервную копию без запроса |
| `--list` | Вывести список доступных резервных копий в формате JSON и выйти |
| `--replace` | Режим замены: перезаписать локальную базу данных вместо слияния |
| `--restore-favicons` | Также восстановить кэш иконок из резервной копии |

!!! info "Слияние и замена"
    Поведение по умолчанию **объединяет** записи из резервной копии с локальной базой данных — записи с обеих сторон сохраняются и дедублируются. Используйте `--replace` только когда хотите полностью перезаписать локальные данные резервной копией.

---

### `db` — Обслуживание Базы Данных

```bash
# VACUUM + ANALYZE (освободить фрагментированное пространство)
hsync db vacuum

# Перестроить индекс полнотекстового поиска
hsync db rebuild-fts

# Нормализовать доменные имена во всех записях
hsync db normalize

# Показать статистику базы данных
hsync db stats
hsync db stats --json
```

**Подкоманды:**

| Подкоманда | Описание |
|---|---|
| `vacuum` | Выполнить `VACUUM` и `ANALYZE` — освободить фрагментированное пространство, обновить статистику планировщика запросов |
| `rebuild-fts` | Перестроить индекс полнотекстового поиска FTS5 — используйте, если поиск медленный или результаты отсутствуют |
| `normalize` | Пересчитать доменные имена для всех записей (полезно после импорта необработанных баз данных) |
| `stats` | Псевдоним для `hsync -S` |

---

### `config` — Управление Настройками

Чтение и запись значений конфигурации без открытия GUI.

```bash
# Вывести все ключи и их текущие значения
hsync config list

# Прочитать одно значение
hsync config get webdav.url

# Записать значение
hsync config set webdav.enabled true
hsync config set webdav.url https://dav.example.com/historysync/
hsync config set scheduler.sync_interval_hours 2
hsync config set theme dark
hsync config set language ru_RU
```

**Настраиваемые ключи:**

| Ключ | Тип | Описание |
|---|---|---|
| `webdav.enabled` | bool | Включить резервное копирование WebDAV |
| `webdav.url` | string | URL WebDAV-сервера |
| `webdav.username` | string | Имя пользователя WebDAV |
| `webdav.remote_path` | string | Удалённый путь для резервных копий (по умолчанию: `/HistorySync/`) |
| `webdav.max_backups` | int | Количество хранимых резервных копий (по умолчанию: `10`) |
| `webdav.verify_ssl` | bool | Проверять SSL-сертификат (по умолчанию: `true`) |
| `webdav.auto_backup` | bool | Включить автоматическое резервное копирование по расписанию |
| `webdav.backup_favicons` | bool | Включать кэш иконок в резервную копию |
| `scheduler.auto_sync_enabled` | bool | Включить автоматическую синхронизацию браузеров |
| `scheduler.sync_interval_hours` | int | Интервал синхронизации в часах |
| `scheduler.auto_backup_enabled` | bool | Включить запланированное WebDAV-резервное копирование |
| `scheduler.auto_backup_interval_hours` | int | Интервал резервного копирования в часах |
| `scheduler.launch_on_startup` | bool | Запускать HistorySync при входе в систему |
| `theme` | string | `dark` \| `light` \| `system` |
| `language` | string | Код языка интерфейса (например: `ru_RU`). Пусто = автоопределение. |

---

<a id="update-check-for-updates"></a>

### `update` — Проверить Обновления

Проверьте, доступен ли более новый релиз HistorySync для текущей платформы и типа установки.

```bash
# Человекочитаемый вывод
hsync update

# Машиночитаемый JSON
hsync update --json

# Проверка канала релизов, отличного от канала по умолчанию
hsync update --channel beta
hsync update --channel nightly
```

**Параметры:**

| Флаг | Описание |
|---|---|
| `--json` | Вывести метаданные обновления в JSON для скриптов и CI |
| `--channel CH` | Временно переопределить канал для этой проверки: `stable` \| `beta` \| `nightly` |

**Что делает команда:**

- Использует те же платформо-зависимые метаданные обновлений, что и desktop-приложение.
- Переходит на метаданные GitHub Releases, если основной API обновлений недоступен.
- Учитывает текущую форму установки при выборе артефактов, например установщик, portable ZIP, AppImage или `.dmg`.

!!! note "CLI только проверяет"
    `hsync update` сообщает о доступности обновления и метаданных. Настоящий пошаговый процесс загрузки и установки находится в **Настройки → Обновления** desktop-приложения.

---

## Автодополнение в Shell

`hsync` поддерживает автодополнение в shell через `argcomplete`.

=== "Bash"
    ```bash
    # Одноразовая глобальная настройка
    activate-global-python-argcomplete --user

    # Или добавьте в ~/.bashrc:
    eval "$(register-python-argcomplete hsync)"
    ```

=== "Zsh"
    ```zsh
    # Добавьте в ~/.zshrc:
    autoload -U bashcompinit && bashcompinit
    eval "$(register-python-argcomplete hsync)"
    ```

=== "Fish"
    ```fish
    register-python-argcomplete --shell fish hsync \
      > ~/.config/fish/completions/hsync.fish
    ```

---

## Примеры Скриптов и CI

```bash
# Синхронизировать и проверить результат
hsync -s -q && echo "sync ok" || echo "sync failed"

# Передать JSON статуса в jq
hsync -S --json | jq .record_count

# Сохранить журнал в файл
hsync -s --no-color 2>&1 | tee sync.log

# Синхронизация + резервное копирование по расписанию (совместимо с cron)
hsync -sb -q

# Экспортировать страницы GitHub за последнюю неделю в JSON
hsync -e github_week.json \
  --domain github.com \
  --after "$(date -d '7 days ago' +%Y-%m-%d)"

# Синхронизация без интерфейса из основного модуля Python (для запланированных задач)
python -m src.main --headless --sync
```

---

## Коды Выхода

| Код | Значение |
|---|---|
| `0` | Успех |
| `1` | Ошибка (подробности выведены в stderr) |
