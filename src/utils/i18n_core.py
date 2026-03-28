# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from collections.abc import Callable
import gettext
import locale
import logging
import os
from pathlib import Path

from src.utils.path_helper import get_locales_dir

log = logging.getLogger(__name__)


def _get_locales_dir() -> str:
    return str(get_locales_dir())


# ── Lightweight signal stub ───────────────────────────────────────────────────
class _SignalStub:
    """Duck-type stand-in for ``PySide6.QtCore.Signal``."""

    def __init__(self) -> None:
        self._callbacks: list[Callable[[], None]] = []

    @property
    def callbacks(self) -> list[Callable[[], None]]:
        """Read-only snapshot of registered callbacks."""
        return list(self._callbacks)

    def connect(self, cb: Callable[[], None]) -> None:
        if cb not in self._callbacks:
            self._callbacks.append(cb)

    def disconnect(self, cb: Callable[[], None]) -> None:
        try:
            self._callbacks.remove(cb)
        except ValueError:
            pass

    def emit(self) -> None:
        for cb in self._callbacks:
            try:
                cb()
            except Exception as exc:
                log.warning("language_changed callback raised: %s", exc)


# ── Core LanguageManager ──────────────────────────────────────────────────────


class LanguageManager:
    """Manages application language and gettext translation loading."""

    # Maps lang_code -> display name
    LANGUAGE_NAMES: dict[str, str] = {
        "en_US": "English",
        "zh_CN": "简体中文",
        "zh_TW": "繁體中文",
        "ja_JP": "日本語",
        "ko_KR": "한국어",
        "fr_FR": "Français",
        "de_DE": "Deutsch",
        "ru_RU": "Русский",
        "es_ES": "Español (España)",
        "pt_BR": "Português (Brasil)",
        "it_IT": "Italiano",
        "pl_PL": "Polski",
        "tr_TR": "Türkçe",
    }

    def __init__(self) -> None:
        self.language_changed: _SignalStub = _SignalStub()

        self.app_name = "historysync"
        self.locale_dir = _get_locales_dir()
        self.default_lang = "en_US"
        self.current_lang_code = self.default_lang
        # Identity function — returns the English key as-is (en_US / no .mo file)
        self._translate: Callable[[str], str] = lambda s: s
        self._supported: list[str] | None = None

    # ── Language discovery ────────────────────────────────────────────────────

    @property
    def supported_languages(self) -> list[str]:
        if self._supported is None:
            self._supported = self._scan_supported()
        return self._supported

    def _scan_supported(self) -> list[str]:
        """Scan locales directory for compiled .mo files."""
        langs: list[str] = []
        locale_path = Path(self.locale_dir)
        if locale_path.is_dir():
            for entry in locale_path.iterdir():
                if entry.is_dir():
                    mo = entry / "LC_MESSAGES" / f"{self.app_name}.mo"
                    if mo.exists():
                        langs.append(entry.name)
        return langs

    def get_system_language(self) -> str | None:
        """Try to determine the OS system language."""
        try:
            sys_lang, _ = locale.getdefaultlocale()
            if sys_lang:
                return sys_lang
        except Exception:
            pass
        env_lang = os.getenv("LANG") or os.getenv("LANGUAGE")
        if env_lang:
            return env_lang.split(".")[0]
        return None

    def get_best_match(self) -> str:
        """Return the best available language for the current system."""
        sys_lang = self.get_system_language()
        if not sys_lang:
            return self.default_lang

        normalized = sys_lang.lower().replace("-", "_")
        supported_lower = {lang.lower(): lang for lang in self.supported_languages}

        # Exact match
        if normalized in supported_lower:
            return supported_lower[normalized]

        # Base-language match (e.g. zh_TW -> zh_CN if only zh_CN available)
        base = normalized.split("_")[0]
        for code_lower, code in supported_lower.items():
            if code_lower.startswith(base):
                return code

        return self.default_lang

    # ── Translation setup ─────────────────────────────────────────────────────

    def setup_translation(self, lang_code: str | None = None) -> None:
        """Load translations for *lang_code*.

        Pass ``None`` to auto-detect from system locale.
        Falls back to English (identity) on any error.
        """
        if lang_code is None:
            lang_code = self.get_best_match()

        previous = self.current_lang_code
        self.current_lang_code = lang_code

        if lang_code == self.default_lang:
            self._translate = lambda s: s
            log.info("Language set to default (en_US)")
            if lang_code != previous:
                self.language_changed.emit()
            return

        try:
            translation = gettext.translation(
                self.app_name,
                localedir=self.locale_dir,
                languages=[lang_code],
                fallback=True,
            )
            translation.install()
            self._translate = translation.gettext
            log.info("Translation loaded for '%s'", lang_code)
        except Exception as exc:
            log.warning(
                "Failed to load translation for '%s': %s — using English",
                lang_code,
                exc,
            )
            self._translate = lambda s: s
            self.current_lang_code = self.default_lang

        if lang_code != previous:
            self.language_changed.emit()

    # ── Public helpers ────────────────────────────────────────────────────────

    def gettext(self, s: str) -> str:
        return self._translate(s)

    def get_current_language(self) -> str:
        return self.current_lang_code

    def get_available_languages(self) -> list[str]:
        """Sorted list of available lang codes; en_US always first."""
        available = sorted(set(self.supported_languages) | {self.default_lang})
        if self.default_lang in available:
            available.remove(self.default_lang)
        return [self.default_lang, *available]

    def get_language_name(self, lang_code: str) -> str:
        return self.LANGUAGE_NAMES.get(lang_code, lang_code)

    def get_available_languages_map(self) -> dict[str, str]:
        return {code: self.get_language_name(code) for code in self.get_available_languages()}


# ── Module-level singleton + shortcuts ───────────────────────────────────────

lang_manager = LanguageManager()


def _(s: str) -> str:
    return lang_manager.gettext(s)


def N_(s: str) -> str:
    """Mark a string for translation without translating it yet (deferred translation).

    Use this for strings stored in module-level data structures (dicts, lists)
    where translation must be deferred to runtime but xgettext still needs to
    extract them.  Pass the result through ``_()`` at the point of display.

    Example::

        _LABELS = {KEY: N_("Some label")}
        widget.setToolTip(_(_LABELS[key]))
    """
    return s
