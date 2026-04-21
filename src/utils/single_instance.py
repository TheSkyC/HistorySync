# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

import logging
from pathlib import Path
import secrets
import tempfile

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QHostAddress, QTcpServer, QTcpSocket

logger = logging.getLogger(__name__)

SINGLE_INSTANCE_PORT = 20455
ACTIVATE_MSG = b"ACTIVATE_HISTORYSYNC"
ACTIVATE_QUICK_MSG = b"ACTIVATE_QUICK"

# ── Nonce-based IPC authentication ───────────────────────────────────────────
# A random nonce is generated at server startup and stored in a user-local temp
# file.  Clients must prefix every message with the nonce bytes so that
# unrelated local processes that know the port number and message format cannot
# trigger activation blindly.
_NONCE_BYTES = 20
_TOKEN_FILE = Path(tempfile.gettempdir()) / "hs_ipc.token"


def _read_nonce() -> bytes:
    """Read the server nonce from the token file.  Returns b'' on any error."""
    try:
        data = _TOKEN_FILE.read_bytes()
        if len(data) == _NONCE_BYTES:
            return data
    except OSError:
        pass
    return b""


class SingleInstanceServer(QObject):
    request_activation = Signal()
    request_quick_overlay = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.server = QTcpServer(self)
        self.server.newConnection.connect(self._handle_new_connection)
        self._nonce: bytes = secrets.token_bytes(_NONCE_BYTES)
        try:
            _TOKEN_FILE.write_bytes(self._nonce)
        except OSError as exc:
            logger.warning("SingleInstanceServer: could not write token file: %s", exc)

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
            _TOKEN_FILE.unlink(missing_ok=True)
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
        payload = data[_NONCE_BYTES:]
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
