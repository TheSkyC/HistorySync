---
title: Installation
description: How to install HistorySync on Windows, macOS, and Linux — both pre-built packages and from source.
---

# Installation

HistorySync runs on **Windows**, **macOS**, and **Linux**. Choose the method that suits you best.

---

## Pre-built Packages (Recommended)

Download the latest release from the **[GitHub Releases](https://github.com/TheSkyC/HistorySync/releases/latest)** page.

=== "Windows"

    | Package | Notes |
    |---|---|
    | `HistorySync-vX.Y.Z-windows-x64-setup.exe` | Full installer, adds a Start Menu entry and optional auto-start |
    | `HistorySync-vX.Y.Z-windows-x64-portable.zip` | Portable — extract and run anywhere, no install needed |

    Run the installer and follow the on-screen instructions. No additional dependencies are required.

=== "macOS"

    | Package | Notes |
    |---|---|
    | `HistorySync-vX.Y.Z-macos-arm64.dmg` | Drag-and-drop installation |

    1. Open the `.dmg` file.
    2. Drag **HistorySync** into your `Applications` folder.
    3. On first launch, macOS may show a security prompt — click **Open** to proceed.

    !!! note "Accessibility permission"
        The global hotkey `Ctrl+Shift+H` requires **Accessibility** permission. macOS will prompt you the first time you use it. Grant access in **System Settings → Privacy & Security → Accessibility**.

=== "Linux"

    | Package | Notes |
    |---|---|
    | `HistorySync-vX.Y.Z-linux-x86_64.AppImage` | Runs on any modern Linux distribution |
    | `HistorySync-vX.Y.Z-linux-x86_64.tar.gz` | Generic tarball for any Linux distribution |
    | `historysync_X.Y.Z_amd64.deb` | For Debian/Ubuntu-based distributions |

    **AppImage:**
    ```bash
    chmod +x HistorySync-*.AppImage
    ./HistorySync-*.AppImage
    ```

    **Debian/Ubuntu `.deb`:**
    ```bash
    sudo dpkg -i HistorySync-*.deb
    sudo apt-get install -f   # fix any missing dependencies
    ```

    !!! warning "Global hotkeys on Linux/Wayland"
        Global hotkeys via `pynput` are **not supported on Wayland**. The `Ctrl+Shift+H` overlay shortcut will not function in a Wayland session. Consider using `--quick` with a system-level keybinding as a workaround (see [Keyboard Shortcuts](keyboard-shortcuts.md)).

---

## Install from Source

Use this method if you want to run the latest development code or contribute to the project.

### Prerequisites

- **Python 3.10+** (Python 3.12 recommended — matches CI)
- **Git**

### Steps

```bash
# 1. Clone the repository
git clone https://github.com/TheSkyC/HistorySync.git
cd HistorySync

# 2. Create and activate a virtual environment (strongly recommended)
python -m venv venv

# Windows
.\venv\Scripts\activate

# macOS / Linux
source venv/bin/activate

# 3. Install runtime dependencies
pip install -r requirements.txt

# 4. Run the application
python -m src.main
```

### Install the `hsync` CLI (optional)

Pre-built `hsync` binaries are available on the **[GitHub Releases](https://github.com/TheSkyC/HistorySync/releases/latest)** page:

| Package | Platform |
|---|---|
| `hsync-vX.Y.Z-windows-x64-setup.exe` | Windows installer |
| `hsync-vX.Y.Z-windows-x64.zip` | Windows portable |
| `hsync-vX.Y.Z-macos-arm64.tar.gz` | macOS (Apple Silicon) |
| `hsync-vX.Y.Z-linux-x86_64.tar.gz` | Linux x86-64 |

Alternatively, the headless CLI can be invoked directly with Python:

```bash
python -m src.cli --help
```

To install it as the `hsync` command on your `PATH`:

```bash
# Create a simple wrapper script (Linux / macOS)
echo '#!/bin/sh\npython -m src.cli "$@"' > /usr/local/bin/hsync
chmod +x /usr/local/bin/hsync
```

---

## Verifying the Installation

Launch the GUI and check the title bar for the version number, or run:

```bash
# GUI
python -m src.main --version

# CLI
python -m src.cli --version
# or if installed:
hsync --version
```

---

## Upgrading

Replace the existing binary with the new one from the Releases page. HistorySync stores its configuration and database separately from the application binary, so upgrading never touches your data.

Default data locations:

| Platform | Directory |
|---|---|
| Windows | `%APPDATA%\HistorySync\` |
| macOS | `~/Library/Application Support/HistorySync/` |
| Linux | `~/.config/HistorySync/` |

You can override this with `--config-dir` or use `--portable` mode to keep all data next to the executable.

---

## Uninstalling

1. Remove the application binary / AppImage / package.
2. Optionally delete the data directory listed above to remove all browsing data and settings.

!!! warning
    Deleting the data directory is irreversible. Back up your database first if you want to keep your history.
