---
title: Contributing
description: Development setup, code style, DCO sign-off, and PR workflow for HistorySync contributors.
---

# Contributing to HistorySync

Thank you for your interest in contributing! Bug fixes, new browser extractors, documentation improvements, translations, and test coverage are especially welcome.

---

## Getting Started

1. **Browse open [Issues](https://github.com/TheSkyC/HistorySync/issues)** — look for labels like `good first issue` or `help wanted`.
2. **Comment on an issue** before starting significant work to avoid duplicate effort.
3. For small fixes (typos, one-line bugs), open a PR directly without a prior issue.

---

## Development Setup

### Prerequisites

| Tool | Required version |
|---|---|
| Python | **3.12** recommended (matches CI environment) |
| Git | Any recent version |

> HistorySync supports Python 3.10+, but use **3.12** when contributing so your environment matches linting, tests, and locked dependencies.

### Steps

```bash
# 1. Fork the repo on GitHub, then clone your fork
git clone https://github.com/YOUR_USERNAME/HistorySync.git
cd HistorySync

# 2. Create and activate a virtual environment
python -m venv venv
source venv/bin/activate     # macOS / Linux
.\venv\Scripts\activate      # Windows

# 3. Install runtime dependencies
pip install -r requirements.txt

# 4. Install development & test dependencies
pip install -r requirements-dev.txt
pip install -r requirements-test.txt

# 5. (Recommended) Install pre-commit hooks
pre-commit install

# 6. Verify the setup
python -m src.main --fresh
```

---

## Code Style

This project uses **[Ruff](https://github.com/astral-sh/ruff)** for linting and formatting. Configuration is in `ruff.toml`.

```bash
# Check for issues
ruff check .

# Auto-fix where possible
ruff check . --fix

# Format code
ruff format .

# Run all pre-commit hooks manually
pre-commit run --all-files
```

**General style notes:**

- Follow the existing patterns in the file you are editing.
- Keep GUI code (PySide6) and business logic **strictly separated** — services must not import Qt.
- Prefer clarity over cleverness.
- Add or update docstrings when changing public APIs.

---

## Running Tests

```bash
# Run the full test suite
pytest

# Run a specific test file
pytest tests/test_chromium_extractor.py

# Verbose output
pytest -v

# With coverage (requires pytest-cov, included in requirements-test.txt)
pytest --cov=src --cov-report=term-missing

# Same lint checks as CI
ruff check src/ tests/
ruff format --check src/ tests/
```

All tests must pass before a PR can be merged. If you add new functionality, please include corresponding tests.

---

## Commit Guidelines

Use clear, imperative commit messages:

```
<type>(<scope>): <subject>
```

**Examples:**
```
fix(extractor): handle missing WAL file during Chromium extraction
feat(browser): add Arc browser support on macOS
docs(webdav): document merge behaviour
test(search): add unit tests for query DSL parser
chore(dev): update Ruff to 0.15
```

**Types:** `fix`, `feat`, `refactor`, `docs`, `test`, `chore`, `perf`, `style`, `ci`, `build`

**Rules:**
- Subject line ≤ 72 characters.
- Use a lowercase imperative verb (`add`, `fix`, `remove` — not `added`, `fixes`).
- Add a body to explain *why* for non-obvious changes.

---

## Developer Certificate of Origin (DCO)

**Every commit must be signed off. PRs with unsigned commits will not be merged.**

```bash
git commit -s -m "fix: handle missing WAL file"
# Appends: Signed-off-by: Your Name <your@email.com>
```

Make sure your Git identity is set:
```bash
git config --global user.name "Your Name"
git config --global user.email "your@email.com"
```

### Forgot to sign off?

```bash
# Last commit only
git commit --amend --no-edit --signoff
git push --force-with-lease

# Multiple commits (last N)
git rebase --signoff HEAD~N
git push --force-with-lease
```

---

## Pull Request Workflow

1. **Create a branch** from `main`:
   ```bash
   git checkout -b fix/edge-history-extraction-utf8
   git checkout -b feat/opera-browser-support
   git checkout -b docs/webdav-setup-guide
   ```

2. **Make your changes** — keep commits focused and atomic.

3. **Run tests and lint** locally.

4. **Push and open a PR** against `main`:
   ```bash
   git push origin your-branch-name
   ```

5. Follow the PR rules:
   - One change or one related set of changes per PR.
   - Clear description of *what* changed and *why*.
   - Link the related issue with `Closes #123`.
   - Add screenshots / recordings for UI changes.
   - Every commit must be signed off.

6. **Respond to review feedback** promptly.

---

## What We're Looking For

**Especially welcome:**

- **New browser extractors** — support for additional Chromium/Firefox forks.
- **Bug fixes** — especially platform-specific issues (macOS paths, Linux permissions, Windows UAC).
- **Performance improvements** — query optimisation, extraction speed, memory usage.
- **UI/UX improvements** — accessibility, keyboard navigation, theme consistency.
- **Test coverage** — new tests for currently untested code paths.
- **Documentation** — improving this site, adding inline docstrings, fixing typos.
- **Translations** — updates to `.po` files under `src/resources/locales/`.

**Discuss first (open an issue before coding):**

- Major architectural changes.
- New third-party dependencies.
- Changes to the WebDAV sync protocol or database schema.

---

## Security Vulnerabilities

**Do not open a public issue for security vulnerabilities.**

Report privately by emailing **security@historysync.app**. Include a description, reproduction steps, and potential impact. You will receive a response within 72 hours.

---

## License

By submitting a pull request, you agree that your contribution will be licensed under **Apache 2.0** and you certify the DCO for every commit.
