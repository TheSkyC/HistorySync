# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
import os
from pathlib import Path
import platform
import re
import threading

from src.utils.logger import get_logger

log = get_logger("browser_scanner")

# Maximum scan depth
MAX_SCAN_DEPTH = 5

# Maximum number of parent directories to look up
MAX_PARENT_LOOKUP = MAX_SCAN_DEPTH

# SQLite magic header
SQLITE_MAGIC = b"SQLite format 3\x00"

# Generic directory names (skipped when extracting browser names)
GENERIC_NAMES = {
    "local",
    "appdata",
    "roaming",
    "application support",
    "library",
    "user data",
    "user",
    "default",
    "profile",
    "profiles",
    "data",
    "config",
    "cache",
    "temp",
    "tmp",
}

# Directories to skip during scanning
SKIP_DIRS = {
    "temp",
    "tmp",
    "cache",
    "logs",
    "log",
    "backup",
    "backups",
    "node_modules",
    ".git",
    ".vscode",
    ".idea",
    "__pycache__",
    "test",
    "tests",
    "pytest",
    "dist",
    "build",
}

# Keywords indicating browser data (prioritized during scan)
BROWSER_KEYWORDS = {"user data", "profiles", "user", "browser", "application support"}


@dataclass
class DetectedBrowser:
    """Represents a detected browser."""

    browser_type: str  # Auto-generated ID, e.g., "detected_liebao"
    display_name: str  # Extracted from path, e.g., "Liebao Browser"
    engine: str  # "chromium" | "firefox" | "safari"
    data_dir: Path  # Path to the data directory
    history_path: Path  # Path to the History/places.sqlite file
    profiles: list[str] = field(default_factory=list)  # List of profile names
    confidence: float = 1.0  # Detection confidence (0.0 - 1.0)


ProgressCallback = Callable[[str, int, int], None]  # (status, current, total)
BrowserFoundCallback = Callable[[DetectedBrowser], None]  # Callback when a browser is found


class BrowserScanner:
    """Smart browser scanner."""

    def __init__(self):
        self._found_browsers: list[DetectedBrowser] = []
        self._scanned_paths: set[Path] = set()
        self._browser_found_callback: BrowserFoundCallback | None = None
        self._stop_event = threading.Event()

        # Set scan depth based on the platform
        system = platform.system()
        if system == "Windows":
            self._max_scan_depth = 4  # Windows requires depth=4
        else:
            self._max_scan_depth = 3  # macOS/Linux uses depth=3

        self._max_parent_lookup = self._max_scan_depth

    def request_stop(self) -> None:
        """Request to stop the scanning process."""
        self._stop_event.set()

    def scan(
        self,
        progress_callback: ProgressCallback | None = None,
        browser_found_callback: BrowserFoundCallback | None = None,
    ) -> list[DetectedBrowser]:
        """
        Scans common directories to discover browsers.

        Returns:
            A list of detected browsers.
        """
        self._found_browsers = []
        self._scanned_paths = set()
        self._browser_found_callback = browser_found_callback
        self._stop_event.clear()

        # Get scan root directories
        scan_roots = self._get_scan_roots()
        log.info("Starting browser scan in %s root directories", len(scan_roots))

        scanned_dirs = 0

        # BFS scan for each root directory
        for root in scan_roots:
            if not root.exists():
                continue

            scanned = self._scan_directory_bfs(
                root,
                lambda current, total, sd=scanned_dirs: (
                    progress_callback(
                        "scanning",
                        sd + current,
                        0,
                    )
                    if progress_callback
                    else None
                ),
            )
            scanned_dirs += scanned

        # Deduplicate: merge different profiles of the same browser
        self._deduplicate_browsers()

        log.info("Scan complete: found %s browsers", len(self._found_browsers))
        return self._found_browsers

    def _get_scan_roots(self) -> list[Path]:
        """Get root directories to start scanning."""
        roots = []
        system = platform.system()

        if system == "Windows":
            # Windows: %LOCALAPPDATA% and %APPDATA%
            if localappdata := os.environ.get("LOCALAPPDATA"):
                roots.append(Path(localappdata))
            if appdata := os.environ.get("APPDATA"):
                roots.append(Path(appdata))
        elif system == "Darwin":
            # macOS: ~/Library/Application Support
            home = Path.home()
            roots.append(home / "Library" / "Application Support")
        else:
            # Linux: ~/.config and ~/.local/share
            home = Path.home()
            roots.append(home / ".config")
            roots.append(home / ".local" / "share")

        return roots

    def _scan_directory_bfs(self, root: Path, progress_callback: Callable[[int, int], None] | None = None) -> int:
        """Perform BFS scan on a directory."""
        queue = deque([(root, 0)])  # (path, depth)
        scanned_count = 0

        while queue:
            if self._stop_event.is_set():
                log.info("Scan stopped by request")
                break

            current_path, depth = queue.popleft()
            scanned_count += 1

            if progress_callback and scanned_count % 10 == 0:
                progress_callback(scanned_count, 0)

            try:
                resolved = current_path.resolve()
            except OSError:
                continue
            if resolved in self._scanned_paths:
                continue
            self._scanned_paths.add(resolved)

            # Check if the directory contains a browser database
            self._check_for_browser_db(current_path)

            # Apply depth limit
            if depth >= self._max_scan_depth:
                continue

            # Continue scanning subdirectories
            try:
                subdirs = []
                priority_subdirs = []

                for item in current_path.iterdir():
                    if not item.is_dir():
                        continue

                    if item.is_symlink():
                        continue

                    # Skip hidden and specific directories
                    if item.name.startswith("."):
                        continue
                    if item.name.lower() in SKIP_DIRS:
                        continue

                    item_lower = item.name.lower()
                    # Prioritize directories containing browser keywords
                    if any(kw in item_lower for kw in BROWSER_KEYWORDS):
                        priority_subdirs.append((item, depth + 1))
                    else:
                        subdirs.append((item, depth + 1))

                # Priority queue: process directories with keywords first
                for item in priority_subdirs + subdirs:
                    queue.append(item)

            except (PermissionError, OSError):
                continue

        return scanned_count

    def _check_for_browser_db(self, path: Path) -> None:
        """Check if the directory contains a browser database."""
        # Check for Chromium History file
        history_file = path / "History"
        if history_file.exists() and self._is_valid_sqlite(history_file):
            self._process_chromium_browser(history_file)

        # Check for Firefox places.sqlite file
        places_file = path / "places.sqlite"
        if places_file.exists() and self._is_valid_sqlite(places_file):
            self._process_firefox_browser(places_file)

    def _is_valid_sqlite(self, file_path: Path) -> bool:
        """Verify if the file is a valid SQLite database."""
        try:
            with file_path.open("rb") as f:
                header = f.read(16)
                return header == SQLITE_MAGIC
        except Exception:
            return False

    def _process_chromium_browser(self, history_path: Path) -> None:
        """Process a detected Chromium browser."""
        try:
            # Look up for the User Data directory
            profile_dir = history_path.parent
            user_data_dir = self._find_user_data_dir(profile_dir)

            if not user_data_dir:
                # Cannot determine User Data directory, use a single profile
                browser_name = self._extract_browser_name(history_path)
                browser_type = self._generate_browser_id(browser_name)

                detected = DetectedBrowser(
                    browser_type=browser_type,
                    display_name=browser_name,
                    engine="chromium",
                    data_dir=profile_dir,
                    history_path=history_path,
                    profiles=[profile_dir.name],
                    confidence=0.7,
                )
                self._found_browsers.append(detected)
                if self._browser_found_callback:
                    self._browser_found_callback(detected)
                log.info("Found Chromium browser: %s at %s", browser_name, profile_dir)
                return

            # Enumerate all profiles
            profiles = self._enumerate_chromium_profiles(user_data_dir)
            if not profiles:
                return

            browser_name = self._extract_browser_name(user_data_dir)
            browser_type = self._generate_browser_id(browser_name)

            detected = DetectedBrowser(
                browser_type=browser_type,
                display_name=browser_name,
                engine="chromium",
                data_dir=user_data_dir,
                history_path=history_path,
                profiles=profiles,
                confidence=0.9,
            )
            self._found_browsers.append(detected)
            if self._browser_found_callback:
                self._browser_found_callback(detected)
            log.info("Found Chromium browser: %s with %s profiles", browser_name, len(profiles))

        except Exception as e:
            log.warning("Error processing Chromium browser at %s: %s", history_path, e)

    def _process_firefox_browser(self, places_path: Path) -> None:
        """Process a detected Firefox browser."""
        try:
            profile_dir = places_path.parent

            # Look up for the Profiles directory
            profiles_dir = self._find_firefox_profiles_dir(profile_dir)

            if not profiles_dir:
                # Single profile
                browser_name = self._extract_browser_name(places_path)
                browser_type = self._generate_browser_id(browser_name)

                detected = DetectedBrowser(
                    browser_type=browser_type,
                    display_name=browser_name,
                    engine="firefox",
                    data_dir=profile_dir,
                    history_path=places_path,
                    profiles=[profile_dir.name],
                    confidence=0.7,
                )
                self._found_browsers.append(detected)
                if self._browser_found_callback:
                    self._browser_found_callback(detected)
                log.info("Found Firefox browser: %s at %s", browser_name, profile_dir)
                return

            # Enumerate all profiles
            profiles = self._enumerate_firefox_profiles(profiles_dir)
            if not profiles:
                return

            browser_name = self._extract_browser_name(profiles_dir)
            browser_type = self._generate_browser_id(browser_name)

            detected = DetectedBrowser(
                browser_type=browser_type,
                display_name=browser_name,
                engine="firefox",
                data_dir=profiles_dir,
                history_path=places_path,
                profiles=profiles,
                confidence=0.9,
            )
            self._found_browsers.append(detected)
            if self._browser_found_callback:
                self._browser_found_callback(detected)
            log.info("Found Firefox browser: %s with %s profiles", browser_name, len(profiles))

        except Exception as e:
            log.warning("Error processing Firefox browser at %s: %s", places_path, e)

    def _find_user_data_dir(self, start_path: Path) -> Path | None:
        """Look up for the Chromium User Data directory."""
        current = start_path
        for _ in range(self._max_parent_lookup):
            if current.name.lower() in ("user data", "user"):
                return current
            if not current.parent or current.parent == current:
                break
            current = current.parent
        return None

    def _find_firefox_profiles_dir(self, start_path: Path) -> Path | None:
        """Look up for the Firefox Profiles directory."""
        current = start_path
        for _ in range(self._max_parent_lookup):
            if current.name.lower() == "profiles":
                return current
            if not current.parent or current.parent == current:
                break
            current = current.parent
        return None

    def _enumerate_chromium_profiles(self, user_data_dir: Path) -> list[str]:
        """Enumerate all Chromium profiles."""
        profiles = []
        try:
            for item in user_data_dir.iterdir():
                if not item.is_dir():
                    continue
                # Check if it contains a History file
                history_file = item / "History"
                if history_file.exists() and self._is_valid_sqlite(history_file):
                    profiles.append(item.name)
        except Exception as e:
            log.warning("Error enumerating Chromium profiles: %s", e)
        return profiles

    def _enumerate_firefox_profiles(self, profiles_dir: Path) -> list[str]:
        """Enumerate all Firefox profiles."""
        profiles = []
        try:
            for item in profiles_dir.iterdir():
                if not item.is_dir():
                    continue
                # Check if it contains a places.sqlite file
                places_file = item / "places.sqlite"
                if places_file.exists() and self._is_valid_sqlite(places_file):
                    profiles.append(item.name)
        except Exception as e:
            log.warning("Error enumerating Firefox profiles: %s", e)
        return profiles

    def _extract_browser_name(self, path: Path) -> str:
        """Extract the browser name from the path."""
        parts = path.parts

        # Look up and skip generic directory names
        for i in range(len(parts) - 1, -1, -1):
            part_lower = parts[i].lower()

            if part_lower in GENERIC_NAMES:
                continue

            # Found the first non-generic name
            name = parts[i]
            return self._clean_browser_name(name)

        # Fallback
        return "Unknown Browser"

    def _clean_browser_name(self, name: str) -> str:
        """Clean up the extracted browser name."""
        # Remove version numbers (e.g., "Chrome 120")
        name = re.sub(r"\s+\d+(\.\d+)*$", "", name)

        # Remove common suffixes
        name = re.sub(r"(?i)\s*(browser|web|app)$", "", name)

        name = name.strip()
        if name:
            # Handle camel case (e.g., "2345Explorer" -> "2345 Explorer")
            name = re.sub(r"([a-z])([A-Z])", r"\1 \2", name)
            # Capitalize words
            name = " ".join(word.capitalize() for word in name.split())

        return name or "Unknown Browser"

    def _generate_browser_id(self, display_name: str) -> str:
        """Generate a unique browser ID."""
        # Convert to lowercase and remove special characters
        browser_id = re.sub(r"[^a-z0-9]+", "_", display_name.lower())
        browser_id = browser_id.strip("_")
        return f"detected_{browser_id}"

    def _deduplicate_browsers(self) -> None:
        """Deduplicate browsers by merging profiles and filtering known ones."""
        from src.services.browser_defs import BUILTIN_BROWSERS

        # Get data directories of known browsers
        known_data_dirs = set()
        for bdef in BUILTIN_BROWSERS:
            for data_dir in bdef.get_data_dirs():
                known_data_dirs.add(str(data_dir).lower())

        # Group by data_dir
        grouped: dict[str, list[DetectedBrowser]] = {}
        for browser in self._found_browsers:
            # Skip known browsers
            data_dir_str = str(browser.data_dir).lower()
            if any(
                data_dir_str.startswith(known_dir.lower()) or known_dir.lower().startswith(data_dir_str)
                for known_dir in known_data_dirs
            ):
                continue

            key = str(browser.data_dir)
            if key not in grouped:
                grouped[key] = []
            grouped[key].append(browser)

        # Merge browsers with the same data_dir
        deduplicated = []
        for browsers in grouped.values():
            if not browsers:
                continue

            # Use the first one as the representative
            main = browsers[0]

            # Merge all profiles
            all_profiles = set()
            for b in browsers:
                all_profiles.update(b.profiles)

            main.profiles = sorted(all_profiles)
            deduplicated.append(main)

        self._found_browsers = deduplicated
        log.info("After deduplication: %s unique browsers", len(self._found_browsers))
