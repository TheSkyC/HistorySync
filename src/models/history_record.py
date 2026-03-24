# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

from dataclasses import dataclass, field


@dataclass
class HistoryRecord:
    """单条归一化历史记录"""

    url: str
    title: str
    visit_time: int  # 10位 Unix 时间戳（秒）
    visit_count: int
    browser_type: str  # 浏览器类型标识符，如 'chrome', 'edge', 'firefox'
    profile_name: str  # 配置文件名，如 'Default', 'default-release'
    metadata: str = ""  # 网页摘要，可能为空

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
