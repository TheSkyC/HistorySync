# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

from dataclasses import dataclass, field


@dataclass
@dataclass
class HistoryRecord:
    # --- 基础必填字段 ---
    url: str
    title: str
    visit_time: int  # 10位 Unix 时间戳（秒）
    visit_count: int
    browser_type: str  # 浏览器类型标识符，如 'chrome', 'edge', 'firefox'
    profile_name: str  # 配置文件名，如 'Default', 'default-release'

    # --- 扩展字段 ---
    metadata: str = ""  # 网页摘要，可能为空

    # 手动在地址栏输入 URL 的次数（Chromium 独有，其余浏览器为 None）
    typed_count: int | None = field(default=None, compare=False)

    # 首次访问时间戳（秒），通过 JOIN visits 表取 MIN() 计算
    first_visit_time: int | None = field(default=None, compare=False)

    # 访问来源类型
    # Chromium: 0=LINK, 1=TYPED, 2=AUTO_BOOKMARK, 7=FORM_SUBMIT, 8=RELOAD 等
    # Firefox: 1=LINK, 2=TYPED, 3=BOOKMARK
    # Safari: None
    transition_type: int | None = field(default=None, compare=False)

    # 最近一次访问的页面停留秒数（Chromium 独有，来自 visits.visit_duration，其余为 None）
    visit_duration: float | None = field(default=None, compare=False)

    # 数据库自增 id（从 DB 读出时填充）
    id: int | None = field(default=None, compare=False)

    def dedup_key(self) -> str:
        """
        去重键：同一浏览器 + 同一 URL + 同一时间戳视为重复
        （处理 Edge 导入 Chrome 历史记录的极端场景）
        """
        return f"{self.browser_type}|{self.url}|{self.visit_time}"


@dataclass
class BackupStats:
    """各浏览器/配置的备份统计元数据"""

    browser_type: str
    profile_name: str
    first_backup_time: int  # 首次备份时间戳
    last_backup_time: int  # 上次成功备份时间戳
    total_records_synced: int  # 累计同步记录数

    id: int | None = field(default=None, compare=False)
