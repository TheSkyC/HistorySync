---
title: CLI 命令参考
description: hsync 命令行工具完整参考 — 所有标志、子命令与高级查询语法。
---

# CLI 命令参考 — `hsync`

`hsync` 是 HistorySync 的**无头 CLI 工具**。它无需 GUI 即可使用应用的全部功能，非常适合定时任务、脚本和 CI 环境。

---

## 全局选项

这些选项适用于所有命令和子命令。

| 标志 | 简写 | 说明 |
|---|---|---|
| `--version` | | 打印版本号并退出 |
| `--config-dir PATH` | | 使用自定义配置/数据目录 |
| `--portable` | | 将所有数据存储在 `hsync` 可执行文件旁边 |
| `--verbose` | `-v` | 启用调试级别日志 |
| `--quiet` | `-q` | 抑制进度输出，仅将错误打印到 stderr |
| `--no-color` | | 禁用 ANSI 颜色（也可通过 `NO_COLOR` 环境变量设置）|
| `--dry-run` | | 探测/验证，不写入任何内容到磁盘或网络 |

---

## 经典操作标志

通过标志执行快捷操作（无需子命令）。

### `-s` / `--sync` — 提取浏览器历史

将浏览器历史导入本地数据库。

```bash
hsync -s
hsync --sync

# 仅同步特定浏览器
hsync -s --browsers chrome,firefox

# 每 30 分钟同步一次（监听模式）
hsync -s -w 30
```

**同步选项：**

| 标志 | 说明 |
|---|---|
| `--browsers LIST` | 以逗号分隔的浏览器类型（默认：所有已检测到的浏览器），例如 `chrome,firefox,edge` |
| `-w 分钟数` / `--watch 分钟数` | 每隔指定分钟数重复同步。按 <kbd>Ctrl</kbd>+<kbd>C</kbd> 停止。 |

### `-b` / `--backup` — WebDAV 备份

将本地数据库的压缩快照上传到 WebDAV。

```bash
hsync -b
hsync --backup

# 同步后立即备份
hsync -sb
```

!!! note "需要先配置 WebDAV"
    使用 `--backup` 前，请先运行 `hsync config set webdav.enabled true` 并设置 URL、用户名和密码。

<a id="export"></a>

### `-e 文件` / `--export 文件` — 导出历史

将浏览历史导出到文件，格式根据文件扩展名自动推断。

```bash
# 导出为 CSV
hsync -e history.csv

# 带过滤器导出为 JSON
hsync -e history.json --keyword python --after 2024-01-01

# 带嵌入图标的 HTML 报告
hsync -e report.html --format html --embed-icons

# 按域名过滤
hsync -e out.csv --domain github.com --domain stackoverflow.com

# 自定义列
hsync -e out.csv --columns title,url,visit_time,browser_type

# 正则表达式关键词过滤
hsync -e out.json --keyword "^https://github" --regex

# 日期范围
hsync -e out.csv --after 2024-01-01 --before 2024-12-31
```

**导出选项：**

| 标志 | 说明 |
|---|---|
| `--format 格式` | `csv` \| `json` \| `html`（默认：根据扩展名推断）|
| `--columns 列名` | 以逗号分隔的列名。可用列：`id`、`title`、`url`、`visit_time`、`visit_count`、`browser_type`、`profile_name`、`domain`、`metadata`、`typed_count`、`first_visit_time`、`transition_type`、`visit_duration` |
| `--embed-icons` | 将网站图标嵌入为 Base64 data-URI（仅 HTML 导出）|
| `--keyword 文本` | 全文关键词过滤 |
| `--regex` | 将 `--keyword` 视为 Python 正则表达式 |
| `--browser 类型` | 按浏览器类型过滤（如 `chrome`、`firefox`、`edge`）|
| `--after 日期` | 包含该日期及之后的记录（`YYYY-MM-DD`）|
| `--before 日期` | 包含该日期及之前的记录（`YYYY-MM-DD`）|
| `--domain 域名` | 限制到指定域名，可重复：`--domain a.com --domain b.com` |

### `-S` / `--status` — 数据库统计

打印数据库统计信息。

```bash
hsync -S
hsync --status

# 机器可读的 JSON 格式
hsync -S --json

# 脚本友好的单行输出
hsync -S -q
```

### `-i` / `--interactive` — 交互式菜单

启动交互式终端菜单，非常适合初次使用。

```bash
hsync -i
hsync --interactive
```

---

## 子命令

### `search` — 搜索历史

使用结构化查询语法搜索历史记录。

```bash
# 浏览最近 20 条记录
hsync search

# 浏览最近 100 条
hsync search --limit 100

# 简单关键词搜索
hsync search python

# 交互模式（支持键盘导航）
hsync search -i

# 结构化查询
hsync search "domain:github.com python"
hsync search "after:2024-01-01 browser:chrome" --limit 50
hsync search "is:bookmarked tag:work" --format json
hsync search "react -tutorial" --open
```

**选项：**

| 标志 | 默认值 | 说明 |
|---|---|---|
| `--limit N` | `20` | 最大结果数 |
| `--format 格式` | `table` | 输出格式：`table` \| `json` \| `tsv` \| `csv` |
| `--columns 列名` | `title,url,visit_time,browser_type` | 显示的列 |
| `--open` | | 在默认浏览器中打开第一条结果 |
| `-i` / `--interactive` | | 带键盘导航的交互模式 |

---

<a id="query-dsl"></a>

### 查询语法

搜索子命令和 GUI 搜索栏都支持丰富的查询语言。

#### 关键词搜索

普通词语在标题和 URL 中搜索：
```
python async
"精确短语"
react -tutorial         # 排除某个词
```

#### 令牌过滤器

| 令牌 | 示例 | 说明 |
|---|---|---|
| `domain:` | `domain:github.com` | 按域名过滤 |
| `title:` | `title:python` | 仅在页面标题中搜索 |
| `url:` | `url:github` | 仅在 URL 中搜索 |
| `after:` | `after:2024-01-01` | 日期范围起始（包含）|
| `before:` | `before:2024-12-31` | 日期范围结束（包含）|
| `browser:` | `browser:chrome` | 按浏览器类型过滤 |
| `device:` | `device:laptop` | 按设备名称或 UUID 过滤 |
| `is:bookmarked` | `is:bookmarked` | 仅已收藏的记录 |
| `has:note` | `has:note` | 仅有批注的记录 |
| `tag:` | `tag:work` | 按书签标签过滤 |

#### 组合查询

令牌和关键词可自由组合：
```
domain:arxiv.org after:2024-01-01 深度学习
is:bookmarked tag:工作 项目管理
browser:firefox -youtube after:2025-01-01
```

---

### `restore` — 从 WebDAV 恢复

从 WebDAV 备份恢复数据库。

```bash
# 列出备份并交互选择
hsync restore

# 自动恢复最新备份（合并模式）
hsync restore --latest

# 以 JSON 格式列出可用备份
hsync restore --list

# 替换模式：完全覆盖本地数据库
hsync restore --replace

# 同时恢复网站图标缓存
hsync restore --latest --restore-favicons
```

!!! info "合并 vs 替换"
    默认行为将备份记录与本地数据库**合并** — 两侧的记录都保留并去重。仅当需要完全用备份覆盖本地数据时，才使用 `--replace`。

---

### `db` — 数据库维护

```bash
# VACUUM + ANALYZE（回收碎片空间）
hsync db vacuum

# 重建全文搜索索引
hsync db rebuild-fts

# 规范化所有记录中的域名
hsync db normalize

# 显示数据库统计
hsync db stats
hsync db stats --json
```

| 子命令 | 说明 |
|---|---|
| `vacuum` | 执行 `VACUUM` 和 `ANALYZE` — 回收碎片空间，更新查询优化器统计信息 |
| `rebuild-fts` | 重建 FTS5 全文搜索索引 — 当搜索缓慢或结果缺失时使用 |
| `normalize` | 重新计算所有记录的域名（导入原始数据库后很有用）|
| `stats` | `hsync -S` 的别名 |

---

### `config` — 管理配置

无需打开 GUI 即可读写配置。

```bash
# 列出所有键及其当前值
hsync config list

# 读取单个值
hsync config get webdav.url

# 写入值
hsync config set webdav.enabled true
hsync config set webdav.url https://dav.example.com/historysync/
hsync config set scheduler.sync_interval_hours 2
hsync config set theme dark
hsync config set language zh_CN
```

**可设置的配置键：**

| 键 | 类型 | 说明 |
|---|---|---|
| `webdav.enabled` | bool | 启用 WebDAV 备份 |
| `webdav.url` | string | WebDAV 服务器 URL |
| `webdav.username` | string | WebDAV 用户名 |
| `webdav.remote_path` | string | 备份远程路径（默认：`/HistorySync/`）|
| `webdav.max_backups` | int | 保留备份数量（默认：`10`）|
| `webdav.verify_ssl` | bool | 验证 SSL 证书（默认：`true`）|
| `webdav.auto_backup` | bool | 启用定期自动备份 |
| `webdav.backup_favicons` | bool | 备份时包含网站图标缓存 |
| `scheduler.auto_sync_enabled` | bool | 启用自动浏览器同步 |
| `scheduler.sync_interval_hours` | int | 同步间隔（小时）|
| `scheduler.auto_backup_enabled` | bool | 启用定期 WebDAV 备份 |
| `scheduler.auto_backup_interval_hours` | int | 备份间隔（小时）|
| `scheduler.launch_on_startup` | bool | 登录时启动 HistorySync |
| `theme` | string | `dark` \| `light` \| `system` |
| `language` | string | UI 语言代码（如 `zh_CN`），留空则自动检测 |

---

## Shell 自动补全

`hsync` 通过 `argcomplete` 支持 Shell 自动补全。

=== "Bash"
    ```bash
    # 一次性全局设置
    activate-global-python-argcomplete --user

    # 或添加到 ~/.bashrc：
    eval "$(register-python-argcomplete hsync)"
    ```

=== "Zsh"
    ```zsh
    # 添加到 ~/.zshrc：
    autoload -U bashcompinit && bashcompinit
    eval "$(register-python-argcomplete hsync)"
    ```

=== "Fish"
    ```fish
    register-python-argcomplete --shell fish hsync \
      > ~/.config/fish/completions/hsync.fish
    ```

---

## 脚本与 CI 示例

```bash
# 同步并检查结果
hsync -s -q && echo "同步成功" || echo "同步失败"

# 将状态 JSON 管道到 jq
hsync -S --json | jq .record_count

# 日志写入文件
hsync -s --no-color 2>&1 | tee sync.log

# 定时同步 + 备份（cron 友好）
hsync -sb -q

# 导出上周的 GitHub 页面为 JSON
hsync -e github_week.json \
  --domain github.com \
  --after "$(date -d '7 days ago' +%Y-%m-%d)"
```

---

## 退出码

| 码 | 含义 |
|---|---|
| `0` | 成功 |
| `1` | 错误（详情打印到 stderr）|
