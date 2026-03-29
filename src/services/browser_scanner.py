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

# 扫描深度限制
MAX_SCAN_DEPTH = 5

# 向上查找父目录的最大层数
MAX_PARENT_LOOKUP = MAX_SCAN_DEPTH

# SQLite magic header
SQLITE_MAGIC = b"SQLite format 3\x00"

# 通用目录名称（跳过这些作为浏览器名称）
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

# 跳过的目录（不扫描）
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

# 浏览器数据特征词（优先处理）
BROWSER_KEYWORDS = {"user data", "profiles", "user", "browser", "application support"}


@dataclass
class DetectedBrowser:
    """扫描发现的浏览器"""

    browser_type: str  # 自动生成ID，如"detected_liebao"
    display_name: str  # 从路径提取，如"Liebao Browser"
    engine: str  # "chromium" | "firefox" | "safari"
    data_dir: Path  # 数据目录路径
    history_path: Path  # History文件路径
    profiles: list[str] = field(default_factory=list)  # profile列表
    confidence: float = 1.0  # 置信度（0-1）


ProgressCallback = Callable[[str, int, int], None]  # (status, current, total)
BrowserFoundCallback = Callable[[DetectedBrowser], None]  # 发现浏览器时的回调


class BrowserScanner:
    """智能浏览器扫描器"""

    def __init__(self):
        self._found_browsers: list[DetectedBrowser] = []
        self._scanned_paths: set[Path] = set()
        self._browser_found_callback: BrowserFoundCallback | None = None
        self._stop_event = threading.Event()

        # 根据平台设置扫描深度
        system = platform.system()
        if system == "Windows":
            self._max_scan_depth = 4  # Windows 需要 depth=4
        else:
            self._max_scan_depth = 3  # macOS/Linux 使用 depth=3

        self._max_parent_lookup = self._max_scan_depth

    def request_stop(self) -> None:
        """请求停止扫描"""
        self._stop_event.set()

    def scan(
        self,
        progress_callback: ProgressCallback | None = None,
        browser_found_callback: BrowserFoundCallback | None = None,
    ) -> list[DetectedBrowser]:
        """
        扫描常见目录，发现浏览器

        Returns:
            发现的浏览器列表
        """
        self._found_browsers = []
        self._scanned_paths = set()
        self._browser_found_callback = browser_found_callback
        self._stop_event.clear()

        # 获取扫描起点
        scan_roots = self._get_scan_roots()
        log.info(f"Starting browser scan in {len(scan_roots)} root directories")

        scanned_dirs = 0

        # BFS扫描每个根目录
        for root in scan_roots:
            if not root.exists():
                continue

            scanned = self._scan_directory_bfs(
                root,
                lambda current, total, sd=scanned_dirs: progress_callback(
                    "scanning",
                    sd + current,
                    0,
                )
                if progress_callback
                else None,
            )
            scanned_dirs += scanned

        # 去重：合并同一浏览器的不同profile
        self._deduplicate_browsers()

        log.info(f"Scan complete: found {len(self._found_browsers)} browsers")
        return self._found_browsers

    def _get_scan_roots(self) -> list[Path]:
        """获取扫描起点目录"""
        roots = []
        system = platform.system()

        if system == "Windows":
            # Windows: %LOCALAPPDATA% 和 %APPDATA%
            if localappdata := os.environ.get("LOCALAPPDATA"):
                roots.append(Path(localappdata))
            if appdata := os.environ.get("APPDATA"):
                roots.append(Path(appdata))
        elif system == "Darwin":
            # macOS: ~/Library/Application Support
            home = Path.home()
            roots.append(home / "Library" / "Application Support")
        else:
            # Linux: ~/.config 和 ~/.local/share
            home = Path.home()
            roots.append(home / ".config")
            roots.append(home / ".local" / "share")

        return roots

    def _scan_directory_bfs(self, root: Path, progress_callback: Callable[[int, int], None] | None = None) -> int:
        """BFS扫描目录"""
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

            # 检查是否包含浏览器数据库
            self._check_for_browser_db(current_path)

            # 深度限制
            if depth >= self._max_scan_depth:
                continue

            # 继续扫描子目录
            try:
                # 优先处理包含浏览器关键词的目录
                subdirs = []
                priority_subdirs = []

                for item in current_path.iterdir():
                    if not item.is_dir():
                        continue

                    if item.is_symlink():
                        continue

                    # 跳过隐藏目录和特定目录
                    if item.name.startswith("."):
                        continue
                    if item.name.lower() in SKIP_DIRS:
                        continue

                    item_lower = item.name.lower()
                    if any(kw in item_lower for kw in BROWSER_KEYWORDS):
                        priority_subdirs.append((item, depth + 1))
                    else:
                        subdirs.append((item, depth + 1))

                # 优先队列：先处理包含关键词的目录
                for item in priority_subdirs + subdirs:
                    queue.append(item)

            except (PermissionError, OSError):
                continue

        return scanned_count

    def _check_for_browser_db(self, path: Path) -> None:
        """检查目录是否包含浏览器数据库"""
        # 检查 Chromium History 文件
        history_file = path / "History"
        if history_file.exists() and self._is_valid_sqlite(history_file):
            self._process_chromium_browser(history_file)

        # 检查 Firefox places.sqlite 文件
        places_file = path / "places.sqlite"
        if places_file.exists() and self._is_valid_sqlite(places_file):
            self._process_firefox_browser(places_file)

    def _is_valid_sqlite(self, file_path: Path) -> bool:
        """验证文件是否为有效的SQLite数据库"""
        try:
            with file_path.open("rb") as f:
                header = f.read(16)
                return header == SQLITE_MAGIC
        except Exception:
            return False

    def _process_chromium_browser(self, history_path: Path) -> None:
        """处理发现的Chromium浏览器"""
        try:
            # 向上查找 User Data 目录
            profile_dir = history_path.parent
            user_data_dir = self._find_user_data_dir(profile_dir)

            if not user_data_dir:
                # 无法确定User Data目录，使用单个profile
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
                log.info(f"Found Chromium browser: {browser_name} at {profile_dir}")
                return

            # 枚举所有profiles
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
            log.info(f"Found Chromium browser: {browser_name} with {len(profiles)} profiles")

        except Exception as e:
            log.warning(f"Error processing Chromium browser at {history_path}: {e}")

    def _process_firefox_browser(self, places_path: Path) -> None:
        """处理发现的Firefox浏览器"""
        try:
            profile_dir = places_path.parent

            # 向上查找Profiles目录
            profiles_dir = self._find_firefox_profiles_dir(profile_dir)

            if not profiles_dir:
                # 单个profile
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
                log.info(f"Found Firefox browser: {browser_name} at {profile_dir}")
                return

            # 枚举所有profiles
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
            log.info(f"Found Firefox browser: {browser_name} with {len(profiles)} profiles")

        except Exception as e:
            log.warning(f"Error processing Firefox browser at {places_path}: {e}")

    def _find_user_data_dir(self, start_path: Path) -> Path | None:
        """向上查找Chromium的User Data目录"""
        current = start_path
        for _ in range(self._max_parent_lookup):
            if current.name.lower() in ("user data", "user"):
                return current
            if not current.parent or current.parent == current:
                break
            current = current.parent
        return None

    def _find_firefox_profiles_dir(self, start_path: Path) -> Path | None:
        """向上查找Firefox的Profiles目录"""
        current = start_path
        for _ in range(self._max_parent_lookup):
            if current.name.lower() == "profiles":
                return current
            if not current.parent or current.parent == current:
                break
            current = current.parent
        return None

    def _enumerate_chromium_profiles(self, user_data_dir: Path) -> list[str]:
        """枚举Chromium的所有profiles"""
        profiles = []
        try:
            for item in user_data_dir.iterdir():
                if not item.is_dir():
                    continue
                # 检查是否包含History文件
                history_file = item / "History"
                if history_file.exists() and self._is_valid_sqlite(history_file):
                    profiles.append(item.name)
        except Exception as e:
            log.warning(f"Error enumerating Chromium profiles: {e}")
        return profiles

    def _enumerate_firefox_profiles(self, profiles_dir: Path) -> list[str]:
        """枚举Firefox的所有profiles"""
        profiles = []
        try:
            for item in profiles_dir.iterdir():
                if not item.is_dir():
                    continue
                # 检查是否包含places.sqlite文件
                places_file = item / "places.sqlite"
                if places_file.exists() and self._is_valid_sqlite(places_file):
                    profiles.append(item.name)
        except Exception as e:
            log.warning(f"Error enumerating Firefox profiles: {e}")
        return profiles

    def _extract_browser_name(self, path: Path) -> str:
        """从路径提取浏览器名称"""
        parts = path.parts

        # 向上查找，跳过通用目录名称
        for i in range(len(parts) - 1, -1, -1):
            part_lower = parts[i].lower()

            # 跳过通用名称
            if part_lower in GENERIC_NAMES:
                continue

            # 找到第一个非通用名称
            name = parts[i]
            return self._clean_browser_name(name)

        # fallback
        return "Unknown Browser"

    def _clean_browser_name(self, name: str) -> str:
        """清理浏览器名称"""
        # 移除版本号 (如 "Chrome 120")
        name = re.sub(r"\s+\d+(\.\d+)*$", "", name)

        # 移除常见后缀
        name = re.sub(r"(?i)\s*(browser|web|app)$", "", name)

        # 首字母大写
        name = name.strip()
        if name:
            # 处理驼峰命名 (如 "2345Explorer" -> "2345 Explorer")
            name = re.sub(r"([a-z])([A-Z])", r"\1 \2", name)
            # 首字母大写
            name = " ".join(word.capitalize() for word in name.split())

        return name or "Unknown Browser"

    def _generate_browser_id(self, display_name: str) -> str:
        """生成浏览器ID"""
        # 转换为小写，移除特殊字符
        browser_id = re.sub(r"[^a-z0-9]+", "_", display_name.lower())
        browser_id = browser_id.strip("_")
        return f"detected_{browser_id}"

    def _deduplicate_browsers(self) -> None:
        """去重：合并同一浏览器的不同profile，过滤已知浏览器"""
        from src.services.browser_defs import BUILTIN_BROWSERS

        # 获取已知浏览器的数据目录
        known_data_dirs = set()
        for bdef in BUILTIN_BROWSERS:
            for data_dir in bdef.get_data_dirs():
                known_data_dirs.add(str(data_dir).lower())

        # 按data_dir分组
        grouped: dict[str, list[DetectedBrowser]] = {}
        for browser in self._found_browsers:
            # 跳过已知浏览器
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

        # 合并同一data_dir的浏览器
        deduplicated = []
        for browsers in grouped.values():
            if not browsers:
                continue

            # 取第一个作为代表
            main = browsers[0]

            # 合并所有profiles
            all_profiles = set()
            for b in browsers:
                all_profiles.update(b.profiles)

            main.profiles = sorted(all_profiles)
            deduplicated.append(main)

        self._found_browsers = deduplicated
        log.info(f"After deduplication: {len(self._found_browsers)} unique browsers")
