# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, QThread, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from src.services.browser_scanner import BrowserScanner, DetectedBrowser
from src.utils.i18n import _
from src.utils.logger import get_logger

log = get_logger("browser_scan_dialog")

_BROWSER_ROLE = Qt.UserRole


class ScanWorker(QThread):
    """扫描工作线程"""

    progress = Signal(str, int, int)  # (status, current, total)
    browser_found = Signal(object)  # DetectedBrowser
    finished = Signal(list)  # list[DetectedBrowser]
    error = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scanner: BrowserScanner | None = None

    def run(self):
        try:
            self._scanner = BrowserScanner()
            results = self._scanner.scan(
                progress_callback=lambda status, current, total: self.progress.emit(status, current, total),
                browser_found_callback=lambda browser: self.browser_found.emit(browser),
            )
            self.finished.emit(results)
        except Exception as e:
            log.error(f"Scan failed: {e}", exc_info=True)
            self.error.emit(str(e))

    def request_stop(self):
        """请求扫描器停止"""
        if self._scanner is not None:
            self._scanner.request_stop()


class BrowserScanDialog(QDialog):
    """浏览器深度扫描对话框"""

    browsers_selected = Signal(list)  # list[DetectedBrowser]

    def __init__(self, parent=None, known_data_dirs: set[str] | None = None):
        super().__init__(parent)
        self.setWindowTitle(_("Deep Browser Scan"))
        self.setModal(True)
        self.resize(600, 500)

        # 已添加的浏览器数据目录
        self._known_data_dirs: set[str] = {d.lower() for d in (known_data_dirs or set())}

        self._detected_browsers: list[DetectedBrowser] = []
        self._worker: ScanWorker | None = None

        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        # 标题
        title = QLabel(_("Scanning for browsers..."))
        title.setStyleSheet("font-size: 14pt; font-weight: bold;")
        layout.addWidget(title)

        # 状态标签
        self._status_label = QLabel(_("Initializing scan..."))
        layout.addWidget(self._status_label)

        # 进度条
        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 100)
        layout.addWidget(self._progress_bar)

        # 结果列表
        self._result_label = QLabel(_("Found browsers:"))
        self._result_label.hide()
        layout.addWidget(self._result_label)

        # 全选/全不选按钮
        self._select_btn_layout = QHBoxLayout()
        self._select_btn_layout.setSpacing(8)
        self._select_btn_layout.setContentsMargins(0, 0, 0, 0)

        self._select_all_btn = QPushButton(_("Select All"))
        self._select_all_btn.setMinimumHeight(32)
        self._select_all_btn.clicked.connect(self._on_select_all)
        self._select_btn_layout.addWidget(self._select_all_btn)

        self._deselect_all_btn = QPushButton(_("Deselect All"))
        self._deselect_all_btn.setMinimumHeight(32)
        self._deselect_all_btn.clicked.connect(self._on_deselect_all)
        self._select_btn_layout.addWidget(self._deselect_all_btn)

        self._select_btn_layout.addStretch()

        self._select_btn_widget = QWidget()
        self._select_btn_widget.setLayout(self._select_btn_layout)
        self._select_btn_widget.hide()
        layout.addWidget(self._select_btn_widget)

        self._browser_list = QListWidget()
        self._browser_list.setSpacing(2)
        self._browser_list.hide()
        self._browser_list.setSelectionMode(QListWidget.NoSelection)
        self._browser_list.setFocusPolicy(Qt.NoFocus)
        self._browser_list.itemClicked.connect(self._on_item_clicked)
        layout.addWidget(self._browser_list)

        # 按钮
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self._cancel_btn = QPushButton(_("Cancel"))
        self._cancel_btn.clicked.connect(self._on_cancel)
        btn_layout.addWidget(self._cancel_btn)

        self._add_btn = QPushButton(_("Add Selected"))
        self._add_btn.clicked.connect(self._on_add_selected)
        self._add_btn.hide()
        btn_layout.addWidget(self._add_btn)

        layout.addLayout(btn_layout)

    def start_scan(self):
        """开始扫描"""
        # 立即显示结果区域
        self._result_label.setText(_("Scanning for browsers..."))
        self._result_label.show()
        self._browser_list.show()
        self._select_btn_widget.show()

        self._worker = ScanWorker(self)
        self._worker.progress.connect(self._on_progress)
        self._worker.browser_found.connect(self._on_browser_found)
        self._worker.finished.connect(self._on_scan_finished)
        self._worker.error.connect(self._on_scan_error)
        self._worker.start()

    def _on_progress(self, status: str, current: int, total: int):
        """更新进度"""
        # 使用不确定进度条
        if self._progress_bar.maximum() != 0:
            self._progress_bar.setMaximum(0)  # 设置为不确定模式

        self._status_label.setText(_("Scanning... ({} directories)").format(current))

    def _is_already_known(self, browser: DetectedBrowser) -> bool:
        """判断此浏览器是否已被添加"""
        if not self._known_data_dirs:
            return False
        data_dir_str = str(browser.data_dir).lower()
        return any(data_dir_str.startswith(known) or known.startswith(data_dir_str) for known in self._known_data_dirs)

    def _on_browser_found(self, browser: DetectedBrowser):
        """实时添加发现的浏览器"""
        if self._is_already_known(browser):
            return
        self._detected_browsers.append(browser)

        item = QListWidgetItem()
        item.setData(_BROWSER_ROLE, browser)
        checkbox = QCheckBox(f"{browser.display_name} ({browser.engine}) - {browser.data_dir}")
        checkbox.setChecked(False)  # 默认不选中
        item.setSizeHint(QSize(0, 36))
        self._browser_list.addItem(item)
        self._browser_list.setItemWidget(item, checkbox)
        self._result_label.setText(_("Found {} browser(s)...").format(len(self._detected_browsers)))

    def _on_scan_finished(self, browsers: list[DetectedBrowser]):
        """扫描完成"""
        browsers = [b for b in browsers if not self._is_already_known(b)]
        self._detected_browsers = browsers
        self._progress_bar.setValue(100)
        self._progress_bar.setMaximum(100)  # 恢复确定模式

        # 更新窗口标题
        self.setWindowTitle(_("Deep Browser Scan - Complete"))

        if not browsers:
            self._status_label.setText(_("No new browsers found."))
            self._browser_list.hide()
            self._select_btn_widget.hide()
            self._cancel_btn.setText(_("Close"))
            return

        # 清空列表并重新填充
        self._browser_list.clear()
        for browser in browsers:
            item = QListWidgetItem()
            item.setData(_BROWSER_ROLE, browser)
            checkbox = QCheckBox(f"{browser.display_name} ({browser.engine}) - {browser.data_dir}")
            checkbox.setChecked(False)
            item.setSizeHint(QSize(0, 36))
            self._browser_list.addItem(item)
            self._browser_list.setItemWidget(item, checkbox)

        # 显示最终结果
        self._status_label.setText(_("Scan complete! Found {} browser(s).").format(len(browsers)))
        self._result_label.setText(_("Found browsers:"))
        self._add_btn.show()
        self._cancel_btn.setText(_("Close"))

    def _on_scan_error(self, error: str):
        """扫描错误"""
        self._status_label.setText(_("Scan failed: {}").format(error))
        self._cancel_btn.setText(_("Close"))
        QMessageBox.warning(self, _("Scan Error"), _("Failed to scan for browsers:\n{}").format(error))

    def _on_cancel(self):
        """取消/关闭"""
        if self._worker and self._worker.isRunning():
            self._worker.request_stop()
            if not self._worker.wait(3000):
                log.warning("Scan worker did not stop in time, abandoning thread")
        self.reject()

    def _on_add_selected(self):
        """添加选中的浏览器"""
        selected = []
        for i in range(self._browser_list.count()):
            item = self._browser_list.item(i)
            checkbox = self._browser_list.itemWidget(item)
            if isinstance(checkbox, QCheckBox) and checkbox.isChecked():
                browser = item.data(_BROWSER_ROLE)
                if browser is not None:
                    selected.append(browser)

        if not selected:
            QMessageBox.information(self, _("No Selection"), _("Please select at least one browser to add."))
            return

        self.browsers_selected.emit(selected)
        self.accept()

    def _on_select_all(self):
        """全选"""
        for i in range(self._browser_list.count()):
            item = self._browser_list.item(i)
            checkbox = self._browser_list.itemWidget(item)
            if isinstance(checkbox, QCheckBox):
                checkbox.setChecked(True)

    def _on_deselect_all(self):
        """全不选"""
        for i in range(self._browser_list.count()):
            item = self._browser_list.item(i)
            checkbox = self._browser_list.itemWidget(item)
            if isinstance(checkbox, QCheckBox):
                checkbox.setChecked(False)

    def _on_item_clicked(self, item: QListWidgetItem):
        checkbox = self._browser_list.itemWidget(item)
        if isinstance(checkbox, QCheckBox):
            checkbox.setChecked(not checkbox.isChecked())
