---
title: 贡献指南
description: HistorySync 的开发环境配置、代码风格、DCO 签署与 PR 工作流。
---

# 贡献指南

欢迎各种形式的贡献！修复 Bug、添加新浏览器提取器、改进文档、翻译和补充测试覆盖率都非常受欢迎。

---

## 开始之前

1. **浏览开放的 [Issues](https://github.com/TheSkyC/HistorySync/issues)** — 寻找 `good first issue` 或 `help wanted` 标签。
2. 在开始重大工作之前**在 Issue 中留言**，避免重复劳动。
3. 对于小修复（拼写错误、单行 Bug），可直接开 PR，无需先创建 Issue。

---

## 开发环境设置

### 前提条件

| 工具 | 版本 |
|---|---|
| Python | **3.12** 推荐（与 CI 环境一致）|
| Git | 任何较新版本 |

### 步骤

```bash
# 1. Fork 仓库后克隆你的 Fork
git clone https://github.com/YOUR_USERNAME/HistorySync.git
cd HistorySync

# 2. 创建并激活虚拟环境
python -m venv venv
source venv/bin/activate     # macOS / Linux
.\venv\Scripts\activate      # Windows

# 3. 安装运行时依赖
pip install -r requirements.txt

# 4. 安装开发与测试依赖
pip install -r requirements-dev.txt
pip install -r requirements-test.txt

# 5. （推荐）安装 pre-commit 钩子
pre-commit install

# 6. 验证安装
python -m src.main --fresh
```

---

## 代码风格

本项目使用 **[Ruff](https://github.com/astral-sh/ruff)** 进行代码检查和格式化，配置文件为 `ruff.toml`。

```bash
# 检查问题
ruff check .

# 自动修复（可修复的问题）
ruff check . --fix

# 格式化代码
ruff format .

# 手动运行所有 pre-commit 钩子
pre-commit run --all-files
```

**通用代码风格说明：**

- 遵循正在编辑的文件中已有的模式。
- GUI 代码（PySide6）与业务逻辑**严格分离** — Service 层不得导入 Qt。
- 优先清晰，而非炫技。
- 修改公共 API 时添加或更新文档字符串。

---

## 运行测试

```bash
# 运行全套测试
pytest

# 运行特定测试文件
pytest tests/test_chromium_extractor.py

# 详细输出
pytest -v

# 带覆盖率报告
pytest --cov=src --cov-report=term-missing

# 与 CI 相同的代码检查
ruff check src/ tests/
ruff format --check src/ tests/
```

所有测试必须通过后 PR 才能合并。如果添加了新功能，请附上对应的测试。

---

## 提交信息规范

使用清晰的祈使式提交信息：

```
<类型>(<范围>): <主题>
```

**示例：**
```
fix(extractor): 修复 Chromium 提取时 WAL 文件缺失的处理
feat(browser): 添加 macOS 上的 Arc 浏览器支持
docs(webdav): 记录合并行为
test(search): 为查询 DSL 解析器添加单元测试
chore(dev): 更新 Ruff 至 0.15
```

**类型：** `fix`、`feat`、`refactor`、`docs`、`test`、`chore`、`perf`、`style`、`ci`、`build`

**规则：**
- 主题行 ≤ 72 个字符。
- 使用小写祈使动词（`add`、`fix`、`remove` — 而非 `added`、`fixes`）。
- 对不明显的改动，在正文中解释*原因*。

---

## 开发者来源证书（DCO）

**每次提交都必须签署。未签署提交的 PR 不会被合并。**

```bash
git commit -s -m "fix: 修复 WAL 文件缺失处理"
# 自动追加：Signed-off-by: 你的姓名 <your@email.com>
```

确保 Git 身份已配置：
```bash
git config --global user.name "你的姓名"
git config --global user.email "your@email.com"
```

### 忘记签署了怎么办？

```bash
# 仅最后一次提交
git commit --amend --no-edit --signoff
git push --force-with-lease

# 多次提交（最后 N 次）
git rebase --signoff HEAD~N
git push --force-with-lease
```

---

## PR 工作流

1. **从 `main` 创建分支：**
   ```bash
   git checkout -b fix/edge-history-extraction-utf8
   git checkout -b feat/opera-browser-support
   git checkout -b docs/webdav-setup-guide
   ```

2. **进行修改** — 保持每次提交专注且原子化。

3. **本地运行测试和代码检查。**

4. **推送并对 `main` 开 PR。**

5. 遵守 PR 规范：
   - 每个 PR 只包含一个或一组相关修改。
   - 清晰描述*修改了什么*以及*为什么*。
   - 使用 `Closes #123` 关联相关 Issue。
   - UI 修改附上截图/录像。
   - 每次提交都必须签署。

6. **及时响应审查反馈。**

---

## 我们特别欢迎

- **新浏览器提取器** — 支持更多 Chromium/Firefox 分支。
- **Bug 修复** — 特别是平台相关问题（macOS 路径、Linux 权限、Windows UAC）。
- **性能优化** — 查询优化、提取速度、内存占用。
- **翻译** — 更新 `src/resources/locales/` 下的 `.po` 文件。
- **文档** — 改进本文档站、添加行内文档字符串、修复错别字。

**请先讨论（编码前先开 Issue）：**

- 重大架构变更。
- 新的第三方依赖。
- WebDAV 同步协议或数据库表结构的更改。
