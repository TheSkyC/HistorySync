---
title: 快速上手
description: 五分钟内完成 HistorySync 配置 — 自动后台同步、云端备份与 Spotlight 速查。
---

# 快速上手

本指南帮助你在 **5 分钟内** 完成配置，实现全自动的浏览器历史备份。

---

## 第一步 — 首次启动

启动 HistorySync。首次运行时，**安装向导**将引导你完成基本配置。

如果从源码运行：
```bash
python -m src.main
```

---

## 第二步 — 同步浏览器

在**仪表盘**中，点击**立即同步**。HistorySync 将：

1. 自动检测系统上已安装的所有浏览器。
2. 使用 WAL 快照安全读取 SQLite 历史数据库 — 浏览器可保持运行状态。
3. 将记录导入 HistorySync 本地数据库。

!!! tip "首次同步耗时较长"
    如果你有跨多个浏览器的多年历史数据，首次同步可能需要一两分钟。后续同步为**增量**模式 — 仅导入新记录。

### 选择性同步

只同步特定浏览器，使用 CLI：
```bash
hsync -s --browsers chrome,firefox
```

---

## 第三步 — 搜索历史记录

### GUI 搜索
在**历史**标签页顶部的搜索栏中输入关键词，结果即时呈现。

### 全局悬浮窗（Spotlight 风格）
在**任意应用程序**中按下 <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>H</kbd> 即可唤出速查悬浮窗，支持 Windows、macOS 和 Linux（X11）。Wayland 环境下请将 `python -m src.main --quick` 绑定到系统级快捷键代替。

自然输入，或使用[高级查询语法](cli-reference.md#query-dsl)：

| 示例查询 | 查找内容 |
|---|---|
| `python async` | 标题或 URL 中含这些词的页面 |
| `domain:github.com` | 仅 GitHub 页面 |
| `after:2024-06-01 domain:arxiv.org` | 2024年6月后浏览的论文 |
| `is:bookmarked tag:work` | 标记为"work"的已收藏页面 |
| `react -tutorial` | React 相关页面，排除教程 |

---

## 第四步 — 开启自动同步

进入**设置 → 自动同步**：

1. 启用**自动同步**。
2. 设置首选间隔（默认：2 小时）。
3. 启用**开机启动**，让 HistorySync 以后台静默模式随系统启动。

从此，浏览器历史记录将持续自动聚合到同一个可搜索数据库中。

---

## 第五步 — 配置云端备份（可选）

WebDAV 备份让你能在新设备上恢复历史记录，或跨设备共享数据。

1. 进入**设置 → WebDAV 云端备份**。
2. 填写 WebDAV 服务器 URL、用户名和密码。
3. 启用**自动备份**并设置间隔。
4. 点击**测试连接**验证配置。

主流服务商的详细配置步骤请参阅 [WebDAV 配置指南](webdav-setup.md)。

---

## 第六步 — 开启更新检查

进入 **设置 → 更新**，决定你希望 HistorySync 如何处理新版本：

1. 保持 **自动检查更新** 开启，以便后台发现新版本。
2. 选择发布通道，例如 **Stable** 或 **Beta**。
3. 设置提醒策略，例如“每周最多提醒一次”，避免过于频繁。
4. 随时点击 **检查更新** 执行手动检查。

检测到新版本后，HistorySync 可以显示更新横幅、打开版本详情对话框，并记住“稍后提醒”或“跳过此版本”的决定。

---

## 第七步 — 托盘模式（后台运行）

配置完成后，关闭主窗口。HistorySync 将最小化到**系统托盘**，继续静默同步和备份。

右键点击托盘图标可以：

- **打开 HistorySync** — 恢复主窗口。
- **立即同步** — 触发即时同步。
- **立即备份** — 触发即时 WebDAV 备份。
- **退出** — 完全停止应用。

---

## 下一步

| 目标 | 文档 |
|---|---|
| 从终端自动化同步 | [CLI 命令参考](cli-reference.md) |
| 从终端检查新版本 | [CLI 命令参考](cli-reference.md#update-check-for-updates) |
| 配置特定 WebDAV 服务商 | [WebDAV 配置](webdav-setup.md) |
| 自定义键盘快捷键 | [键盘快捷键](keyboard-shortcuts.md) |
| 导出历史记录为 CSV / JSON / HTML | [CLI 参考 — 导出历史](cli-reference.md#export) |
| 了解安全架构 | [安全架构](../dev/security.md) |
