# Contributing to HistorySync

Thank you for your interest in **HistorySync**! Contributions of all kinds are welcome — bug fixes, new browser extractors, documentation improvements, translations, and test coverage are especially appreciated.

Please read this guide before opening an issue or submitting a pull request.

---

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [Getting Started](#getting-started)
- [Development Setup](#development-setup)
- [Code Style](#code-style)
- [Running Tests](#running-tests)
- [How to Contribute](#how-to-contribute)
  - [Reporting Bugs](#reporting-bugs)
  - [Suggesting Features](#suggesting-features)
  - [Submitting a Pull Request](#submitting-a-pull-request)
- [Commit Guidelines](#commit-guidelines)
- [Developer Certificate of Origin (DCO)](#developer-certificate-of-origin-dco)
- [What We're Looking For](#what-were-looking-for)
- [Security](#security)
- [License](#license)

---

## Code of Conduct

This project follows the [Contributor Covenant Code of Conduct](https://www.contributor-covenant.org/version/2/1/code_of_conduct/). By participating, you agree to uphold a respectful and inclusive environment for everyone.

---

## Getting Started

1. **Browse open [Issues](https://github.com/TheSkyC/HistorySync/issues)** — look for labels like `good first issue` or `help wanted`.
2. **Comment on an issue** before starting significant work so we can coordinate and avoid duplicate effort.
3. For small fixes (typos, one-line bugs), you can open a PR directly without a prior issue.

---

## Development Setup

### Prerequisites

- Git
- Python **3.12** recommended for contributors (matches the CI environment)

HistorySync releases currently support Python 3.10+, but if you are contributing code, use Python 3.12 so your local environment stays aligned with linting, tests, and dependency locks.

### Steps

```bash
# 1. Fork the repo on GitHub, then clone your fork
git clone https://github.com/YOUR_USERNAME/HistorySync.git
cd HistorySync

# 2. Create and activate a virtual environment (strongly recommended)
python -m venv venv

# Windows
.\venv\Scripts\activate
# macOS / Linux
source venv/bin/activate

# 3. Install runtime dependencies
pip install -r requirements.txt

# 4. Install development & test dependencies
pip install -r requirements-dev.txt
pip install -r requirements-test.txt

# 5. (Optional but recommended) Install pre-commit hooks
pre-commit install

# 6. Run the application to verify your setup
python -m src.main
```

> **Hotkey note**: HistorySync uses `pynput` for global hotkeys. On Windows, running as a regular user is sufficient. On macOS, Accessibility permission may be required. On Linux/X11, additional input permissions may be required. Linux/Wayland does not support global hotkeys through `pynput`.

---

## Code Style

This project uses **[Ruff](https://github.com/astral-sh/ruff)** for linting and formatting. The configuration lives in `ruff.toml` at the project root.

```bash
# Check for issues
ruff check .

# Auto-fix where possible
ruff check . --fix

# Format code
ruff format .
```

If you installed the pre-commit hooks (step 5 above), the configured checks will run automatically on every commit. CI also enforces Ruff and the test suite on pull requests, so please make sure your changes pass locally before pushing.

**General style notes:**
- Follow existing patterns in the file you're editing.
- Keep GUI code (PySide6) and business logic cleanly separated.
- Prefer clarity over cleverness.

You can also run the full local hook set manually:

```bash
pre-commit run --all-files
```

---

## Running Tests

```bash
# Run the full test suite
pytest

# Run a specific test file
pytest tests/test_chromium_extractor.py

# Run with verbose output
pytest -v

# Run and show coverage (requires pytest-cov)
pytest --cov=src

# Run the same lint checks used in CI
ruff check src/ tests/
ruff format --check src/ tests/
```

All tests must pass before a PR can be merged. If you add new functionality, please include corresponding tests.

---

## How to Contribute

### Reporting Bugs

Before filing a bug report, please:
1. Search [existing issues](https://github.com/TheSkyC/HistorySync/issues) to avoid duplicates.
2. Reproduce the issue on the **latest release**.

When opening a bug report, include:
- **HistorySync version** (visible in the title bar or About dialog)
- **Operating system** and version
- **Browser(s)** involved (name, version, profile path if relevant)
- **Steps to reproduce** — be as specific as possible
- **Expected vs. actual behavior**
- **Logs or error messages** (check the app's log output or `hsync` CLI output)

### Suggesting Features

Open a [Feature Request](https://github.com/TheSkyC/HistorySync/issues/new?template=feature_request.yml) issue and describe:
- The problem you're trying to solve
- Your proposed solution
- Any alternatives you've considered

For large features, consider starting a [Discussion](https://github.com/TheSkyC/HistorySync/discussions) first.

### Submitting a Pull Request

1. **Create a branch** from `main` with a descriptive name:
   ```bash
   # For bug fixes
   git checkout -b fix/edge-history-extraction-utf8

   # For new features
   git checkout -b feat/opera-browser-support

   # For documentation
   git checkout -b docs/update-webdav-setup-guide
   ```

2. **Make your changes**, keeping commits focused and atomic.

3. **Run the full test suite** and confirm everything passes.

4. **Push your branch** and open a PR against `main`:
   ```bash
   git push origin your-branch-name
   ```

5. Follow the PR rules below:
   - Open the PR against `main` unless the maintainer asks for a different target branch.
   - Keep each PR focused on one change or one related set of changes.
   - Include a clear description of what changed and why.
   - Link the related issue with `Closes #123` when applicable.
   - Add screenshots or recordings for UI changes.
   - Make sure every commit in the PR is signed off.
   - Keep the branch up to date and resolve review feedback promptly.

6. **Respond to review feedback** promptly. The maintainer will review your PR and may request changes before merging.

> **Pull request flow**: Open contributions against `main` through a pull request rather than pushing changes directly.

> **Pull request rule**: A PR should be small, self-contained, and reviewable. If a change touches unrelated code paths, split it into separate PRs.

---

## Commit Guidelines

Use clear, imperative commit messages in the format `<type>(<scope>): <subject>`. A few examples:

```
fix(extractor): handle missing WAL file during Chromium extraction
feat(browser): add Arc browser support on macOS
refactor(extractor): split extractor base class into separate module
docs(webdav): document merge behavior
test(search): add unit tests for query DSL parser
chore(dev): update Ruff tooling
```

Recommended types: `fix`, `feat`, `refactor`, `docs`, `test`, `chore`, `perf`, `style`, `ci`, `build`.

Keep the subject line under 72 characters, start the subject with a lowercase imperative verb, and add a body if the change needs more explanation.

### Commit body (optional but recommended for larger changes)

When a commit touches multiple files, changes architecture, or introduces non-obvious logic, include a body to explain:

- **What**: the specific changes made
- **Why**: the problem being solved or motivation
- **How**: implementation details, if relevant

Separate the subject from the body with a blank line. Each body line should be wrapped at ~72 characters. Example:

```
feat(extractor): add support for Chromium profile detection

Add automatic detection of non-standard Chromium data directories by
scanning common OS paths. This eliminates the need for users to manually
specify profile locations for portable or custom Chromium installations.

The scanner uses breadth-first search to avoid deep recursion and includes
a 10-second timeout to prevent hangs on slow storage.

Closes #156
```

**When to include a body:**
- Your change affects multiple modules or layers
- The fix is non-obvious (e.g., workaround for a subtle bug)
- The change adds significant new functionality
- You need to explain migration steps or breaking changes

**When a body is optional:**
- Typo fixes or simple one-line bugs with clear subject lines
- Obvious refactors that rename or reorganize with no logic change
- Dependencies or tooling bumps with clear version numbers

---

## Developer Certificate of Origin (DCO)

**All commits must be signed off. PRs with unsigned commits will not be merged.**

By signing off, you certify that you wrote the code yourself (or have the right to submit it), and that you agree it may be distributed under the project's license. This is required to protect the project's ability to relicense or commercialize in the future.

### How to sign off

Add `-s` (or `--signoff`) to every commit:

```bash
git commit -s -m "fix: handle missing WAL file during Chromium extraction"
```

This appends the following line to your commit message automatically:

```
Signed-off-by: Your Name <your@email.com>
```

Git uses your configured `user.name` and `user.email`. Make sure they are set:

```bash
git config --global user.name "Your Name"
git config --global user.email "your@email.com"
```

### Forgot to sign off?

**Last commit only:**
```bash
git commit --amend --no-edit --signoff
git push --force-with-lease
```

**Multiple commits:**
```bash
# Sign off the last N commits (replace N with the count)
git rebase --signoff HEAD~N
git push --force-with-lease
```

### Automated enforcement

This repository uses the DCO GitHub app to check every commit in every PR. If any commit is missing a `Signed-off-by` line, the DCO check will fail and the PR cannot be merged until all commits are signed.

### The full DCO text

> Developer Certificate of Origin, Version 1.1
>
> By making a contribution to this project, I certify that:
>
> (a) The contribution was created in whole or in part by me and I have the right to submit it under the open source license indicated in the file; or
>
> (b) The contribution is based upon previous work that, to the best of my knowledge, is covered under an appropriate open source license and I have the right under that license to submit that work with modifications, whether created in whole or in part by me, under the same open source license (unless I am permitted to submit under a different license), as indicated in the file; or
>
> (c) The contribution was provided directly to me by some other person who certified (a), (b) or (c) and I have not modified it.
>
> (d) I understand and agree that this project and the contribution are public and that a record of the contribution (including all personal information I submit with it, including my sign-off) is maintained indefinitely and may be redistributed consistent with this project or the open source license(s) involved.

---

## What We're Looking For

**Especially welcome:**
- **New browser extractors** — support for additional Chromium/Firefox forks, or less common browsers (file an issue first to discuss the approach)
- **Bug fixes** — especially for platform-specific issues (macOS path handling, Linux permissions, Windows UAC)
- **Performance improvements** — query optimization, extraction speed, memory usage
- **UI/UX improvements** — accessibility, keyboard navigation, theme consistency
- **Test coverage** — new tests for existing untested code paths
- **Documentation** — improving the README, adding inline docstrings, fixing typos
- **Translations** — updates to gettext locale files under `src/resources/locales/` (primarily `.po` files; maintainers can regenerate `.mo` artifacts if needed)
- **CLI (`hsync`) improvements** — new flags, better error messages, scripting support

**Please discuss first (open an issue before coding):**
- Major architectural changes
- New third-party dependencies
- Changes to the WebDAV sync protocol or database schema

---

## Security

**Do not open a public issue for security vulnerabilities.**

If you discover a security issue (e.g., a path traversal in WebDAV sync, credential exposure), please report it privately by emailing the maintainer directly:

📧 **0x4fe6@gmail.com**

Include a description of the issue, steps to reproduce, and potential impact. You will receive a response within 72 hours. We will coordinate a fix and disclosure timeline with you.

---

## License

HistorySync is licensed under the [Apache License 2.0](LICENSE).

By submitting a pull request, you agree that your contribution will be licensed under Apache 2.0, and you certify the [Developer Certificate of Origin](#developer-certificate-of-origin-dco) for every commit.

---

**Thank you for helping make HistorySync better!** 🚀
