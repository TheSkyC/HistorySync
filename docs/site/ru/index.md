---
title: HistorySync — Единое управление историей браузера
description: Полная документация HistorySync — мощного кроссплатформенного настольного приложения для управления историей браузера и облачного резервного копирования через WebDAV.
hide:
  - navigation
  - toc
---

<div class="hs-hero" markdown>

<p>
  <img src="../assets/historysync-banner.svg" alt="HistorySync banner" width="360">
</p>

**Единое управление историей браузера и облачное резервное копирование для 30+ браузеров**

<div class="hs-badges" markdown>

[![Release](https://img.shields.io/github/v/release/TheSkyC/HistorySync?style=flat-square)](https://github.com/TheSkyC/HistorySync/releases/latest)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://github.com/TheSkyC/HistorySync/blob/main/LICENSE)
[![Python](https://img.shields.io/badge/Python-3.10%2B-blue?style=flat-square&logo=python)](https://www.python.org/)

</div>

<div class="hs-button-group" markdown>

[Скачать последнюю версию :material-download:](#загрузка){ .md-button .md-button--primary }
[Смотреть на GitHub :material-github:](https://github.com/TheSkyC/HistorySync){ .md-button }

</div>

</div>

## Что такое HistorySync?

**HistorySync** — это мощное кроссплатформенное настольное приложение, которое даёт вам полный контроль над данными браузера. Оно объединяет историю из всех ваших браузеров в единую базу данных с возможностью поиска — и надёжно хранит её в облаке.

<div class="hs-grid">

<div class="hs-card">
<svg class="hs-card-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M2 12h20M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/></svg>
<strong>30+ Браузеров</strong>
<p>Нативная поддержка Chrome, Edge, Firefox, Safari, Brave, Vivaldi, Arc и десятков других — включая региональные браузеры.</p>
</div>

<div class="hs-card">
<svg class="hs-card-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/></svg>
<strong>Поиск в стиле Spotlight</strong>
<p>Нажмите <code>Ctrl+Shift+H</code> в любом приложении, чтобы открыть мгновенное поисковое наложение. Используйте расширенный DSL запросов для поиска чего угодно за миллисекунды.</p>
</div>

<div class="hs-card">
<svg class="hs-card-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M18 10h-1.26A8 8 0 1 0 9 20h9a5 5 0 0 0 0-10z"/></svg>
<strong>Синхронизация через WebDAV</strong>
<p>Атомарная потоковая загрузка на любой WebDAV-сервер. Умное объединение данных с нескольких устройств при восстановлении.</p>
</div>

<div class="hs-card">
<svg class="hs-card-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M22 12h-4l-3 9L9 3l-3 9H2"/></svg>
<strong>Производительность на миллионах записей</strong>
<p>Постраничная навигация по ключевому набору и поиск по регулярным выражениям на уровне SQL обеспечивают плавную прокрутку даже на огромных наборах данных.</p>
</div>

<div class="hs-card">
<svg class="hs-card-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><polyline points="4 17 10 11 4 5"/><line x1="12" y1="19" x2="20" y2="19"/></svg>
<strong>Командная строка (<code>hsync</code>)</strong>
<p>Автоматизируйте синхронизацию, резервное копирование, экспорт и поиск из командной строки — идеально для запланированных задач и CI.</p>
</div>

<div class="hs-card">
<svg class="hs-card-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>
<strong>Приватность прежде всего</strong>
<p>Учётные данные зашифрованы с HKDF, чёрные списки доменов, мягкое скрытие записей и специальный вид для скрытых записей.</p>
</div>

</div>

---

## Загрузка

<div class="hs-download-grid" markdown>

<div class="hs-dl-card" markdown>
**Windows**

[Установщик (.exe)]({{ gh_repo }}/releases/download/v{{ app_version }}/HistorySync-v{{ app_version }}-windows-x64-setup.exe){ .md-button .md-button--primary }
[Портативная версия (.zip)]({{ gh_repo }}/releases/download/v{{ app_version }}/HistorySync-v{{ app_version }}-windows-x64-portable.zip){ .md-button }
</div>

<div class="hs-dl-card" markdown>
**macOS**

[Образ диска (.dmg)]({{ gh_repo }}/releases/download/v{{ app_version }}/HistorySync-v{{ app_version }}-macos-arm64.dmg){ .md-button .md-button--primary }
</div>

<div class="hs-dl-card" markdown>
**Linux**

[AppImage]({{ gh_repo }}/releases/download/v{{ app_version }}/HistorySync-v{{ app_version }}-linux-x86_64.AppImage){ .md-button .md-button--primary }
[Пакет .deb]({{ gh_repo }}/releases/download/v{{ app_version }}/historysync_{{ app_version }}_amd64.deb){ .md-button }
</div>

</div>

> Все пакеты находятся на странице **[GitHub Releases]({{ gh_repo }}/releases/latest)**. Кнопки выше всегда указывают на последнюю версию.

---

## Быстрые Ссылки

<div class="hs-grid">

<div class="hs-card">
<svg class="hs-card-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>
<strong><a href="guide/quick-start/">Быстрый Старт</a></strong>
<p>Запустите приложение за пять минут с автоматической фоновой синхронизацией.</p>
</div>

<div class="hs-card">
<svg class="hs-card-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><polyline points="4 17 10 11 4 5"/><line x1="12" y1="19" x2="20" y2="19"/></svg>
<strong><a href="guide/cli-reference/">Справочник CLI</a></strong>
<p>Полный справочник по инструменту командной строки <code>hsync</code>.</p>
</div>

<div class="hs-card">
<svg class="hs-card-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="2" width="20" height="8" rx="2" ry="2"/><rect x="2" y="14" width="20" height="8" rx="2" ry="2"/><line x1="6" y1="6" x2="6.01" y2="6"/><line x1="6" y1="18" x2="6.01" y2="18"/></svg>
<strong><a href="guide/webdav-setup/">Настройка WebDAV</a></strong>
<p>Пошаговое руководство для популярных WebDAV-провайдеров.</p>
</div>

<div class="hs-card">
<svg class="hs-card-icon hs-card-icon--fill" viewBox="0 0 16 16" fill="currentColor"><path d="M14 5a1 1 0 0 1 1 1v5a1 1 0 0 1-1 1H2a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1zM2 4a2 2 0 0 0-2 2v5a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V6a2 2 0 0 0-2-2z"/><path d="M13 10.25a.25.25 0 0 1 .25-.25h.5a.25.25 0 0 1 .25.25v.5a.25.25 0 0 1-.25.25h-.5a.25.25 0 0 1-.25-.25zm0-2a.25.25 0 0 1 .25-.25h.5a.25.25 0 0 1 .25.25v.5a.25.25 0 0 1-.25.25h-.5a.25.25 0 0 1-.25-.25zm-5 0A.25.25 0 0 1 8.25 8h.5a.25.25 0 0 1 .25.25v.5a.25.25 0 0 1-.25.25h-.5A.25.25 0 0 1 8 8.75zm2 0a.25.25 0 0 1 .25-.25h1.5a.25.25 0 0 1 .25.25v.5a.25.25 0 0 1-.25.25h-1.5a.25.25 0 0 1-.25-.25zm1 2a.25.25 0 0 1 .25-.25h.5a.25.25 0 0 1 .25.25v.5a.25.25 0 0 1-.25.25h-.5a.25.25 0 0 1-.25-.25zm-5-2A.25.25 0 0 1 6.25 8h.5a.25.25 0 0 1 .25.25v.5a.25.25 0 0 1-.25.25h-.5A.25.25 0 0 1 6 8.75zm-2 0A.25.25 0 0 1 4.25 8h.5a.25.25 0 0 1 .25.25v.5a.25.25 0 0 1-.25.25h-.5A.25.25 0 0 1 4 8.75zm-2 0A.25.25 0 0 1 2.25 8h.5a.25.25 0 0 1 .25.25v.5a.25.25 0 0 1-.25.25h-.5A.25.25 0 0 1 2 8.75zm11-2a.25.25 0 0 1 .25-.25h.5a.25.25 0 0 1 .25.25v.5a.25.25 0 0 1-.25.25h-.5a.25.25 0 0 1-.25-.25zm-2 0a.25.25 0 0 1 .25-.25h.5a.25.25 0 0 1 .25.25v.5a.25.25 0 0 1-.25.25h-.5a.25.25 0 0 1-.25-.25zm-2 0A.25.25 0 0 1 9.25 6h.5a.25.25 0 0 1 .25.25v.5a.25.25 0 0 1-.25.25h-.5A.25.25 0 0 1 9 6.75zm-2 0A.25.25 0 0 1 7.25 6h.5a.25.25 0 0 1 .25.25v.5a.25.25 0 0 1-.25.25h-.5A.25.25 0 0 1 7 6.75zm-2 0A.25.25 0 0 1 5.25 6h.5a.25.25 0 0 1 .25.25v.5a.25.25 0 0 1-.25.25h-.5A.25.25 0 0 1 5 6.75zm-3 0A.25.25 0 0 1 2.25 6h1.5a.25.25 0 0 1 .25.25v.5a.25.25 0 0 1-.25.25h-1.5A.25.25 0 0 1 2 6.75zm0 4a.25.25 0 0 1 .25-.25h.5a.25.25 0 0 1 .25.25v.5a.25.25 0 0 1-.25.25h-.5a.25.25 0 0 1-.25-.25zm2 0a.25.25 0 0 1 .25-.25h5.5a.25.25 0 0 1 .25.25v.5a.25.25 0 0 1-.25.25h-5.5a.25.25 0 0 1-.25-.25z"/></svg>
<strong><a href="guide/keyboard-shortcuts/">Сочетания Клавиш</a></strong>
<p>Все 25 настраиваемых сочетания, включая одну глобальную горячую клавишу и 24 привязки внутри приложения.</p>
</div>

<div class="hs-card">
<svg class="hs-card-icon hs-card-icon--fill" viewBox="0 0 16 16" fill="currentColor"><path fill-rule="evenodd" d="M6 3.5A1.5 1.5 0 0 1 7.5 2h1A1.5 1.5 0 0 1 10 3.5v1A1.5 1.5 0 0 1 8.5 6v1H14a.5.5 0 0 1 .5.5v1a.5.5 0 0 1-1 0V8h-5v.5a.5.5 0 0 1-1 0V8h-5v.5a.5.5 0 0 1-1 0v-1A.5.5 0 0 1 2 7h5.5V6A1.5 1.5 0 0 1 6 4.5zM8.5 5a.5.5 0 0 0 .5-.5v-1a.5.5 0 0 0-.5-.5h-1a.5.5 0 0 0-.5.5v1a.5.5 0 0 0 .5.5zM0 11.5A1.5 1.5 0 0 1 1.5 10h1A1.5 1.5 0 0 1 4 11.5v1A1.5 1.5 0 0 1 2.5 14h-1A1.5 1.5 0 0 1 0 12.5zm1.5-.5a.5.5 0 0 0-.5.5v1a.5.5 0 0 0 .5.5h1a.5.5 0 0 0 .5-.5v-1a.5.5 0 0 0-.5-.5zm4.5.5A1.5 1.5 0 0 1 7.5 10h1a1.5 1.5 0 0 1 1.5 1.5v1A1.5 1.5 0 0 1 8.5 14h-1A1.5 1.5 0 0 1 6 12.5zm1.5-.5a.5.5 0 0 0-.5.5v1a.5.5 0 0 0 .5.5h1a.5.5 0 0 0 .5-.5v-1a.5.5 0 0 0-.5-.5zm4.5.5a1.5 1.5 0 0 1 1.5-1.5h1a1.5 1.5 0 0 1 1.5 1.5v1a1.5 1.5 0 0 1-1.5 1.5h-1a1.5 1.5 0 0 1-1.5-1.5zm1.5-.5a.5.5 0 0 0-.5.5v1a.5.5 0 0 0 .5.5h1a.5.5 0 0 0 .5-.5v-1a.5.5 0 0 0-.5-.5z"/></svg>
<strong><a href="dev/architecture/">Архитектура</a></strong>
<p>Диаграмма слоёв MVVM и обзор модулей для участников разработки.</p>
</div>

<div class="hs-card">
<svg class="hs-card-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="18" cy="18" r="3"/><circle cx="6" cy="6" r="3"/><path d="M13 6h3a2 2 0 0 1 2 2v7"/><line x1="6" y1="9" x2="6" y2="21"/></svg>
<strong><a href="dev/contributing/">Участие</a></strong>
<p>Подпись DCO, стиль кода и рабочий процесс pull request.</p>
</div>

</div>
