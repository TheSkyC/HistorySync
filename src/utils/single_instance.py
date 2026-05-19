# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

import logging
import os
from pathlib import Path
import secrets
import sys

from src.utils.path_helper import get_config_dir

logger = logging.getLogger(__name__)


def _get_single_instance_port() -> int:
    base_port = 20455
    if sys.platform == "win32":
        # Windows desktop is typically single-user per session; fixed port avoids
        # cross-version detection failures caused by hash() randomisation.
        return base_port
    # On Linux/macOS offset by UID so concurrent multi-user sessions don't collide.
    return base_port + (os.getuid() % 10000)


SINGLE_INSTANCE_PORT = _get_single_instance_port()
ACTIVATE_MSG = b"ACTIVATE_HISTORYSYNC"
ACTIVATE_QUICK_MSG = b"ACTIVATE_QUICK"

# ── Nonce-based IPC authentication ───────────────────────────────────────────
# A random nonce is generated at server startup and stored in a user-local temp
# file.  Clients must prefix every message with the nonce bytes so that
# unrelated local processes that know the port number and message format cannot
# trigger activation blindly.
_NONCE_BYTES = 20


def _get_token_file() -> Path:
    """Return the IPC token file path, resolved at call time after runtime paths are set."""
    return get_config_dir() / "ipc.token"


def _read_nonce() -> bytes:
    """Read the server nonce from the token file.  Returns b'' on any error."""
    try:
        data = _get_token_file().read_bytes()
        if len(data) == _NONCE_BYTES:
            return data
    except OSError:
        pass
    return b""


# Qt-dependent classes and functions are defined only when PySide6 is available.
# In headless CLI and test environments the constants and _read_nonce() above
# are sufficient; guarding the import avoids a hard PySide6 dependency there.
try:
    from PySide6.QtCore import QObject, Signal
    from PySide6.QtNetwork import QHostAddress, QTcpServer, QTcpSocket

    class SingleInstanceServer(QObject):
        request_activation = Signal()
        request_quick_overlay = Signal()

        def __init__(self, parent=None):
            super().__init__(parent)
            self.server = QTcpServer(self)
            self.server.newConnection.connect(self._handle_new_connection)
            self._nonce: bytes = secrets.token_bytes(_NONCE_BYTES)
            try:
                token_file = _get_token_file()
                token_file.parent.mkdir(parents=True, exist_ok=True)
                token_file.write_bytes(self._nonce)
                if sys.platform != "win32":
                    token_file.chmod(0o600)
            except OSError as exc:
                logger.warning(
                    "SingleInstanceServer: could not write token file, falling back to no-auth mode: %s", exc
                )
                self._nonce = b""  # clients reading b"" from missing file will still match

        def start(self) -> bool:
            if not self.server.listen(QHostAddress.LocalHost, SINGLE_INSTANCE_PORT):
                logger.debug(
                    "SingleInstanceServer: port %d already in use — another instance is likely running",
                    SINGLE_INSTANCE_PORT,
                )
                return False
            logger.debug("SingleInstanceServer: listening on port %d", SINGLE_INSTANCE_PORT)
            return True

        def stop(self) -> None:
            """Close the server and remove the token file."""
            self.server.close()
            try:
                _get_token_file().unlink(missing_ok=True)
            except OSError:
                pass

        def _handle_new_connection(self):
            socket = self.server.nextPendingConnection()
            socket.readyRead.connect(lambda: self._read_data(socket))

        def _read_data(self, socket: QTcpSocket):
            data = socket.readAll().data()
            # Validate nonce prefix before processing the message.
            if not data.startswith(self._nonce):
                logger.warning("SingleInstanceServer: rejected message with invalid or missing nonce")
                socket.disconnectFromHost()
                return
            payload = data[len(self._nonce) :]
            if payload == ACTIVATE_MSG:
                logger.debug("SingleInstanceServer: activation request received")
                self.request_activation.emit()
            elif payload == ACTIVATE_QUICK_MSG:
                logger.debug("SingleInstanceServer: quick overlay request received")
                self.request_quick_overlay.emit()
            socket.disconnectFromHost()

    def raise_existing_instance() -> bool:
        socket = QTcpSocket()
        socket.connectToHost(QHostAddress.LocalHost, SINGLE_INSTANCE_PORT)

        if socket.waitForConnected(50):
            nonce = _read_nonce()
            socket.write(nonce + ACTIVATE_MSG)
            socket.waitForBytesWritten(50)
            socket.disconnectFromHost()
            logger.debug("raise_existing_instance: activation message sent")
            return True

        logger.debug("raise_existing_instance: no existing instance found")
        return False

except ImportError:
    pass


def send_quick_overlay() -> bool:
    """Send ACTIVATE_QUICK_MSG using stdlib socket (no Qt import needed).

    Used by the --quick CLI path so the process starts in ~70ms instead of
    pulling in the full Qt import chain.  Returns True if a running instance
    was found and the message was delivered.
    """
    import socket as _socket

    try:
        with _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM) as s:
            s.settimeout(0.05)
            s.connect(("127.0.0.1", SINGLE_INSTANCE_PORT))
            nonce = _read_nonce()
            s.sendall(nonce + ACTIVATE_QUICK_MSG)
            return True
    except Exception:
        return False
