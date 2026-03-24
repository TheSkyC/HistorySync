# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

import logging

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QHostAddress, QTcpServer, QTcpSocket

logger = logging.getLogger(__name__)

SINGLE_INSTANCE_PORT = 20455
ACTIVATE_MSG = b"ACTIVATE_HISTORYSYNC"


class SingleInstanceServer(QObject):
    request_activation = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.server = QTcpServer(self)
        self.server.newConnection.connect(self._handle_new_connection)

    def start(self) -> bool:
        if not self.server.listen(QHostAddress.LocalHost, SINGLE_INSTANCE_PORT):
            logger.debug(
                "SingleInstanceServer: port %d already in use — another instance is likely running",
                SINGLE_INSTANCE_PORT,
            )
            return False
        logger.debug("SingleInstanceServer: listening on port %d", SINGLE_INSTANCE_PORT)
        return True

    def _handle_new_connection(self):
        socket = self.server.nextPendingConnection()
        socket.readyRead.connect(lambda: self._read_data(socket))

    def _read_data(self, socket: QTcpSocket):
        data = socket.readAll().data()
        if data == ACTIVATE_MSG:
            logger.debug("SingleInstanceServer: activation request received")
            self.request_activation.emit()
        socket.disconnectFromHost()


def raise_existing_instance() -> bool:
    socket = QTcpSocket()
    socket.connectToHost(QHostAddress.LocalHost, SINGLE_INSTANCE_PORT)

    if socket.waitForConnected(50):
        socket.write(ACTIVATE_MSG)
        socket.waitForBytesWritten(50)
        socket.disconnectFromHost()
        logger.debug("raise_existing_instance: activation message sent")
        return True

    logger.debug("raise_existing_instance: no existing instance found")
    return False
