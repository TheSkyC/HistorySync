---
title: 键盘快捷键
description: HistorySync 全部 25 个可配置键盘快捷键 — 1 个全局热键与 24 个应用内绑定。
---

# 键盘快捷键

HistorySync 提供 **25 个可配置的快捷键** — 1 个全局热键和 24 个应用内绑定。所有快捷键均可在**设置 → 键盘快捷键**中修改。

---

## 全局热键

此快捷键在系统范围内有效 — 即使 HistorySync 在后台运行或最小化到托盘，也能触发。

| 操作 | 默认 | 说明 |
|---|---|---|
| **打开速查悬浮窗** | <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>H</kbd> | 唤出 / 隐藏 Spotlight 风格的搜索悬浮窗 |

!!! info "Linux / Wayland"
    `pynput` 的全局热键**不支持 Wayland**。可使用 `--quick` 配合桌面环境的系统级快捷键绑定作为替代：
    ```bash
    # 在 DE 设置中将此命令绑定到系统快捷键
    python -m src.main --quick
    ```

!!! info "macOS"
    全局热键首次触发时，macOS 会请求**辅助功能**权限。请在**系统设置 → 隐私与安全 → 辅助功能**中授权。

---

## 应用内快捷键

这些快捷键在 HistorySync 窗口获得焦点时有效。

### 当前默认值

| 分类 | 默认快捷键 |
|---|---|
| **页面导航** | 仪表板 <kbd>Ctrl</kbd>+<kbd>1</kbd>，历史 <kbd>Ctrl</kbd>+<kbd>2</kbd>，书签 <kbd>Ctrl</kbd>+<kbd>3</kbd>，设置 <kbd>Ctrl</kbd>+<kbd>4</kbd>，日志 <kbd>Ctrl</kbd>+<kbd>5</kbd>，统计 <kbd>Ctrl</kbd>+<kbd>6</kbd> |
| **全局操作** | 立即同步 <kbd>Ctrl</kbd>+<kbd>R</kbd>，聚焦搜索 <kbd>Ctrl</kbd>+<kbd>F</kbd> |
| **历史页** | 打开选中项 <kbd>Enter</kbd>，删除选中项 <kbd>Delete</kbd>，复制 URL <kbd>Ctrl</kbd>+<kbd>C</kbd>，复制标题 + URL <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>C</kbd>，切换书签 <kbd>Ctrl</kbd>+<kbd>B</kbd>，添加批注 <kbd>Ctrl</kbd>+<kbd>N</kbd>，打开导出 <kbd>Ctrl</kbd>+<kbd>E</kbd>，隐藏选中项默认未分配 |
| **书签页** | 打开 <kbd>Enter</kbd>，复制 URL <kbd>Ctrl</kbd>+<kbd>C</kbd>，删除 <kbd>Delete</kbd>，添加批注 <kbd>Ctrl</kbd>+<kbd>N</kbd>，在历史中定位 <kbd>Ctrl</kbd>+<kbd>L</kbd> |
| **统计页** | 上一周期 <kbd>Alt</kbd>+<kbd>Left</kbd>，下一周期 <kbd>Alt</kbd>+<kbd>Right</kbd> |
| **设置页** | 保存 <kbd>Ctrl</kbd>+<kbd>S</kbd> |

设置对话框才是最终事实来源。留空的快捷键表示它默认未绑定，需由你自行分配。

---

## 自定义快捷键

1. 进入**设置 → 键盘快捷键**。
2. 点击要修改的快捷键。
3. 按下新的组合键。
4. 点击**保存**。

要**禁用**某个快捷键，点击它后按 <kbd>Backspace</kbd> 或 <kbd>Delete</kbd> 清除。

!!! warning "快捷键冲突"
    如果两个操作使用相同的组合键，最后设置的那个生效。设置对话框会对冲突显示警告图标。

---

## 速查悬浮窗内的快捷键

这些快捷键在悬浮窗（`Ctrl+Shift+H` 面板）内有效：

| 操作 | 按键 |
|---|---|
| **浏览结果** | <kbd>↑</kbd> / <kbd>↓</kbd> |
| **打开选中的 URL** | <kbd>Enter</kbd> |
| **在新标签页打开**（如果浏览器支持）| <kbd>Ctrl</kbd>+<kbd>Enter</kbd> |
| **关闭悬浮窗** | <kbd>Esc</kbd> |
| **清空搜索** | <kbd>Ctrl</kbd>+<kbd>A</kbd> 然后 <kbd>Delete</kbd> |
