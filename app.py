"""Native desktop UI. Run with Python 3.15 and PySide6-Essentials."""
from __future__ import annotations

import json
from pathlib import Path
import re
import sys
import threading
from collections import deque

from PySide6.QtCore import QObject, Signal, QUrl, Qt, QTimer, QSize
from PySide6.QtGui import QDesktopServices, QFont, QTextCursor, QColor, QPainter, QIcon, QSyntaxHighlighter, QTextCharFormat
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QFileDialog,
                              QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
                              QMainWindow, QMessageBox, QPlainTextEdit, QProgressBar,
                              QPushButton, QSizePolicy, QVBoxLayout, QWidget, QStyledItemDelegate,
                              QStyleOptionViewItem, QStyleOptionComboBox, QStyle, QDialog, QDialogButtonBox, QScrollArea, QFrame, QTabWidget, QListWidget, QListWidgetItem, QInputDialog)
from release_info import APP_NAME, VERSION
from project_config import effective_options, remember_options, options_changed, validate_options
from build_config_panel import BuildConfigPanel
from backend import Builder, capture, inspect_project, scan_devices, scan_simulators, scan_teams, check_dependencies, installed_creator_versions, simulator_catalog, create_simulator, delete_simulator, set_simulator_power, simulator_app_processes, restart_simulator


class Events(QObject):
    log = Signal(str)
    stage = Signal(str)
    finished = Signal(str, bool)
    scanned = Signal(object, str)
    teams = Signal(object)
    running = Signal(object)
    dependencies = Signal(object)
    simulator_action = Signal(object)
    platform_counts = Signal(object)


from log_style import LogHighlighter
from device_combo import BOOTED_ROLE, DeviceDelegate, ReadableComboBox, RefreshHint


def icon_button(name, label):
    button = QPushButton()
    button.setIcon(QIcon(str(Path(__file__).parent / f"icon-{name}.svg")))
    button.setIconSize(QSize(18, 18))
    button.setFixedSize(34, 34)
    button.setStyleSheet("padding: 6px;")
    button.setToolTip(label)
    button.setAccessibleName(label)
    return button


class CreateSimulatorDialog(QDialog):
    def __init__(self, catalog, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Tạo máy ảo iPhone")
        self.setMinimumWidth(480)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.runtime = ReadableComboBox()
        self.model = ReadableComboBox()
        self.name = QLineEdit("iPhone Test")
        self.name.setMaxLength(100)
        for runtime in catalog:
            self.runtime.addItem(runtime["name"], runtime)
        self.runtime.currentIndexChanged.connect(self.update_models)
        self.update_models()
        form.addRow("Phiên bản iOS", self.runtime)
        form.addRow("Mẫu iPhone", self.model)
        form.addRow("Tên máy ảo", self.name)
        layout.addLayout(form)
        note = QLabel("Chỉ hiện iOS đã cài và tương thích với phiên bản Cocos của project.\nTạo xong, chọn Build & Run để cài và mở app.")
        note.setWordWrap(True)
        layout.addWidget(note)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Tạo máy ảo")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Hủy")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self.name.textChanged.connect(lambda text: buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(bool(text.strip())))
        layout.addWidget(buttons)

    def update_models(self):
        self.model.clear()
        for model in self.runtime.currentData()["types"]:
            self.model.addItem(model["name"], model["id"])


class DropArea(QLabel):
    dropped = Signal(str)

    def __init__(self):
        super().__init__("Kéo thư mục project Cocos vào đây\nhoặc bấm Chọn project")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumHeight(88)
        self.setAcceptDrops(True)
        self.setObjectName("drop")

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        urls = event.mimeData().urls()
        if len(urls) == 1 and urls[0].isLocalFile():
            self.dropped.emit(urls[0].toLocalFile())
            event.acceptProposedAction()


class Window(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} {VERSION}")
        available = QApplication.primaryScreen().availableGeometry()
        self.resize(int(available.width() * 0.9), int(available.height() * 0.9))
        self.move(available.center() - self.rect().center())
        self.info = None
        self.builder = None
        self.devices = []
        self.pending_log = []
        self.log_history = deque(maxlen=5000)
        self.running_scan = False
        self.booted_simulators = []
        self.dependency_check_id = 0
        self.sim_busy = False
        self.checking_build = False
        self.pending_build_only = False
        self.pending_launch = None
        self.pending_project = None
        self.pending_log_device = None
        self.pending_shutdown_device = None
        self.pending_restart_device = None
        self.preferred_simulator = None
        self.events = Events()
        self.events.log.connect(self.append_log)
        self.events.stage.connect(self.status_update)
        self.events.finished.connect(self.finished)
        self.events.scanned.connect(self.scanned)
        self.events.teams.connect(self.teams_loaded)
        self.events.running.connect(self.running_updated)
        self.events.dependencies.connect(self.dependencies_updated)
        self.events.simulator_action.connect(self.simulator_action_done)
        self.settings_path = Path.home() / "Library/Application Support/Cocos iOS Builder/settings.json"
        try:
            self.settings = json.loads(self.settings_path.read_text())
        except (OSError, ValueError):
            self.settings = {"projects": {}}
        self.settings.setdefault("projects", {})
        central = QWidget()
        central.setObjectName("content")
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(central)
        shell = QWidget()
        shell_layout = QHBoxLayout(shell)
        shell_layout.setContentsMargins(0,0,0,0)
        sidebar = QWidget()
        sidebar.setFixedWidth(210)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.addWidget(QLabel("PROJECTS"))
        self.project_list = QListWidget()
        self.project_list.itemClicked.connect(lambda item: self.load_project(item.data(Qt.ItemDataRole.UserRole)))
        sidebar_layout.addWidget(self.project_list,1)
        add_project = QPushButton("＋ Thêm project")
        add_project.clicked.connect(self.choose_project)
        sidebar_layout.addWidget(add_project)
        rename_project = QPushButton("Đổi tên")
        rename_project.clicked.connect(self.rename_project)
        sidebar_layout.addWidget(rename_project)
        remove_project = QPushButton("Bỏ khỏi danh sách")
        remove_project.clicked.connect(self.remove_project)
        sidebar_layout.addWidget(remove_project)
        shell_layout.addWidget(sidebar)
        self.platform_tabs = QTabWidget()
        self.platform_tabs.addTab(scroll, 'iOS')
        from android_panel import AndroidPanel
        self.android_panel = AndroidPanel(self)
        android_scroll = QScrollArea()
        android_scroll.setWidgetResizable(True)
        android_scroll.setFrameShape(QFrame.Shape.NoFrame)
        android_scroll.setWidget(self.android_panel)
        self.platform_tabs.addTab(android_scroll, 'Android')
        self.platform_tabs.setCurrentIndex(1 if self.settings.get('platform') == 'android' else 0)
        self.platform_tabs.currentChanged.connect(self.platform_changed)
        from platform_status import PlatformStatus, platform_icon
        from PySide6.QtWidgets import QTabBar
        self.platform_badges = [PlatformStatus(self.platform_tabs), PlatformStatus(self.platform_tabs)]
        for index, badge in enumerate(self.platform_badges):
            self.platform_tabs.setTabIcon(index, platform_icon(index == 1))
            side = QTabBar.ButtonPosition.LeftSide if index == 0 else QTabBar.ButtonPosition.RightSide
            self.platform_tabs.tabBar().setTabButton(index, side, badge)
        self.platform_device_counts = [None, None]
        self.platform_count_scanning = False
        self.platform_tick = 0
        self.events.platform_counts.connect(self.platform_counts_updated)
        self.platform_status_timer = QTimer(self)
        self.platform_status_timer.timeout.connect(self.refresh_platform_status)
        self.platform_status_timer.start(200)
        shell_layout.addWidget(self.platform_tabs,1)
        self.setCentralWidget(shell)
        self.refresh_projects()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(24, 20, 24, 20)
        title = QLabel(APP_NAME)
        title.setFont(QFont("Arial", 25, QFont.Weight.Bold))
        layout.addWidget(title)
        version_label = QLabel(f"v{VERSION} · Build, cài và chạy app · Python {sys.version.split()[0]} · Không cần mở Xcode")
        version_label.setWordWrap(True)
        layout.addWidget(version_label)
        self.drop = DropArea()
        self.drop.dropped.connect(self.load_project)
        layout.addWidget(self.drop)
        self.project_path = QLineEdit()
        self.project_path.setPlaceholderText("Đường dẫn project Cocos Creator 3.x")
        self.project_path.editingFinished.connect(self.project_edited)
        choose = QPushButton("Chọn project…")
        choose.clicked.connect(self.choose_project)
        row = QHBoxLayout()
        row.addWidget(self.project_path, 1)
        row.addWidget(choose)
        layout.addLayout(row)
        self.dependency_panel = QGroupBox("Kiểm tra công cụ")
        dependency_layout = QVBoxLayout(self.dependency_panel)
        self.dependency_notice = QLabel("Chọn project để kiểm tra Cocos và Xcode.")
        self.dependency_notice.setWordWrap(True)
        dependency_layout.addWidget(self.dependency_notice)
        installed_form = QFormLayout()
        self.installed_cocos = QLineEdit()
        self.installed_cocos.setReadOnly(True)
        self.installed_cocos.setPlaceholderText("Đang kiểm tra…")
        installed_form.addRow("Cocos đã cài", self.installed_cocos)
        dependency_layout.addLayout(installed_form)
        dependency_actions = QHBoxLayout()
        self.dashboard_button = QPushButton("Mở Cocos Dashboard / Tải về")
        self.dashboard_button.clicked.connect(self.open_dashboard)
        self.dashboard_button.hide()
        dependency_actions.addWidget(self.dashboard_button)
        self.xcode_button = QPushButton("Tải Xcode")
        self.xcode_button.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("https://apps.apple.com/app/xcode/id497799835")))
        self.xcode_button.hide()
        dependency_actions.addWidget(self.xcode_button)
        self.recheck_button = QPushButton("Kiểm tra lại")
        self.recheck_button.clicked.connect(lambda: self.check_tools())
        dependency_actions.addWidget(self.recheck_button)
        dependency_actions.addStretch()
        dependency_layout.addLayout(dependency_actions)
        group = QGroupBox("Build & thiết bị")
        form = QFormLayout(group)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        form.addRow(self.dependency_panel)
        self.config = ReadableComboBox()
        self.config.currentIndexChanged.connect(self.config_changed)
        form.addRow("Cấu hình Cocos", self.config)
        self.mode = ReadableComboBox()
        self.mode.addItem("iPhone thật (USB / thiết bị đã ghép đôi)", "device")
        self.mode.addItem("iOS Simulator (máy ảo)", "simulator")
        self.mode.currentIndexChanged.connect(self.mode_changed)
        target_form = QFormLayout()
        target_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        target_form.addRow("Chạy trên", self.mode)
        row = QHBoxLayout()
        self.device = ReadableComboBox()
        self.device.setItemDelegate(DeviceDelegate(self.device))
        self.refresh = icon_button("refresh", "Làm mới danh sách thiết bị")
        self.refresh.clicked.connect(self.scan)
        self.refresh_hint = RefreshHint(self.refresh, lambda: self.mode.currentData() == 'simulator' and not self.device.currentData() and not self.builder and not self.sim_busy)
        self.device.currentIndexChanged.connect(self.refresh_hint.sync)
        self.mode.currentIndexChanged.connect(self.refresh_hint.sync)
        row.addWidget(self.device)
        row.addWidget(self.refresh)
        self.create_sim = icon_button("create", "Tạo máy ảo")
        self.create_sim.clicked.connect(self.new_simulator)
        row.addWidget(self.create_sim)
        self.delete_sim = icon_button("delete", "Xóa máy ảo đang chọn")
        self.delete_sim.clicked.connect(self.remove_simulator)
        row.addWidget(self.delete_sim)
        self.device.currentIndexChanged.connect(self.update_simulator_buttons)
        row.addStretch()
        target_form.addRow("Thiết bị", row)
        layout.addLayout(target_form)
        live_row = QHBoxLayout()
        self.live = QLabel("Chưa có simulator đang bật")
        self.live.setWordWrap(True)
        self.show_sim = icon_button("reload", "Reload máy ảo về idle · Không tự chạy game")
        self.show_sim.clicked.connect(self.restart_selected_simulator)
        self.show_sim.setEnabled(False)
        live_row.addWidget(self.live, 1)
        live_row.addWidget(self.show_sim)
        self.power_off_sim = icon_button("power", "Tắt máy ảo đang chọn")
        self.power_off_sim.clicked.connect(self.shutdown_simulator)
        self.power_off_sim.setEnabled(False)
        live_row.addWidget(self.power_off_sim)
        layout.addLayout(live_row)
        self.team = ReadableComboBox()
        self.team.setEditable(True)
        self.team.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        form.addRow("Apple Team ID", self.team)
        self.bundle = QLineEdit()
        self.bundle.setPlaceholderText("com.company.game.debug")
        form.addRow("Bundle ID", self.bundle)
        row = QHBoxLayout()
        self.creator = QLineEdit()
        self.creator.setPlaceholderText("Tự nhận diện phiên bản từ package.json")
        self.creator.editingFinished.connect(lambda: self.check_tools())
        creator_choose = QPushButton("Chọn Cocos…")
        creator_choose.clicked.connect(self.choose_creator)
        row.addWidget(self.creator, 1)
        row.addWidget(creator_choose)
        form.addRow("Cocos Creator", row)
        self.build_config = BuildConfigPanel()
        self.build_config.changed.connect(self.save_current_project)
        self.build_config.reset_requested.connect(self.reset_build_config)
        form.addRow(self.build_config)
        self.native_only = QCheckBox("Chỉ build native từ bản xuất Cocos đã có")
        form.addRow(self.native_only)
        self.reuse_existing = QCheckBox("Dùng output/cache hiện có của cấu hình Cocos (nhanh hơn)")
        self.reuse_existing.setChecked(True)
        form.addRow(self.reuse_existing)
        self.force_export = QCheckBox("Buộc xuất lại Cocos, kể cả khi asset/script không đổi")
        form.addRow(self.force_export)
        self.console = QCheckBox("Thu log độc lập sau khi Run (Dừng/đóng tool không tắt game)")
        self.console.setChecked(True)
        form.addRow(self.console)
        advanced = QPushButton("Cài đặt ▸")
        self.advanced = advanced
        advanced.setCheckable(True)
        advanced.toggled.connect(group.setVisible)
        advanced.toggled.connect(lambda checked: advanced.setText("Cài đặt ▾" if checked else "Cài đặt ▸"))
        layout.addWidget(advanced)
        layout.addWidget(group)
        group.setVisible(False)
        self.controls = group
        self.run_notice = QLabel()
        self.run_notice.setWordWrap(True)
        self.run_notice.setStyleSheet("color: #ffd18a; font-size: 12px;")
        layout.addWidget(self.run_notice)
        row = QHBoxLayout()
        self.build_only_button = QPushButton("Build")
        self.build_only_button.setMinimumHeight(40)
        self.build_only_button.setToolTip("Xuất Cocos và biên dịch app, không cài/chạy; không cần chọn thiết bị.")
        self.build_only_button.clicked.connect(lambda: self.start_build(build_only=True))
        self.build_button = QPushButton("Build && Run")
        self.run_button = QPushButton("Run")
        self.run_button.setMinimumHeight(40)
        self.run_button.setToolTip("Cài và mở app đã build trên thiết bị đang chọn; bỏ qua Cocos và biên dịch. Dùng nội dung của bản build cũ.")
        self.run_button.clicked.connect(lambda: self.begin_build(run_only=True))
        self.clean_run_button = QPushButton("Clean && Run")
        self.clean_run_button.setMinimumHeight(40)
        self.clean_run_button.setEnabled(False)
        self.clean_run_button.setToolTip("Xóa app và dữ liệu trên thiết bị đã chọn, cài bản đã build mới nhất rồi chạy; không build lại.")
        self.clean_run_button.clicked.connect(self.confirm_clean_run)
        self.build_button.setObjectName("primary")
        self.build_button.setEnabled(False)
        self.run_button.setEnabled(False)
        if hasattr(self, "clean_run_button"):
            self.clean_run_button.setEnabled(False)
        self.build_only_button.setEnabled(False)
        self.build_button.setMinimumHeight(40)
        self.build_button.clicked.connect(lambda: self.start_build())
        self.stop = QPushButton("Dừng")
        self.stop.setEnabled(False)
        self.stop.clicked.connect(self.cancel)
        row.addWidget(self.build_only_button)
        row.addWidget(self.build_button, 1)
        row.addWidget(self.run_button)
        row.addWidget(self.clean_run_button)
        row.addWidget(self.stop)
        layout.addLayout(row)
        self.status = QLabel("Chọn project để bắt đầu")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        self.progress.setMaximumHeight(5)
        layout.addWidget(self.progress)
        device_log_row = QHBoxLayout()
        device_log_row.addWidget(QLabel("Device log"))
        self.device_log = ReadableComboBox()
        self.device_log.setToolTip("Chỉ đổi nguồn log; không cài, mở lại hoặc đóng game")
        self.device_log.addItem("Chọn máy để xem log…", None)
        self.device_log.currentIndexChanged.connect(self.log_device_changed)
        device_log_row.addWidget(self.device_log)
        device_log_row.addStretch()
        layout.addLayout(device_log_row)
        log_bar = QHBoxLayout()
        self.log_filter = QLineEdit()
        self.log_filter.setPlaceholderText("Lọc log theo nội dung…")
        self.log_filter.setClearButtonEnabled(True)
        self.log_filter.textChanged.connect(self.refresh_log_view)
        self.log_level = ReadableComboBox()
        self.log_level.setMinimumContentsLength(8)
        self.log_level.setFixedWidth(140)
        self.log_level.addItem("Tất cả", "all")
        self.log_level.addItem("Error", "error")
        self.log_level.addItem("Warning", "warning")
        self.log_level.currentIndexChanged.connect(self.refresh_log_view)
        self.log_count = QLabel("0 dòng")
        clear_log = QPushButton("Clear log")
        clear_log.setToolTip("Xóa log trên màn hình; file log của lượt build vẫn được giữ.")
        clear_log.clicked.connect(self.clear_log_view)
        log_bar.addWidget(self.log_filter, 1)
        log_bar.addWidget(self.log_level)
        log_bar.addWidget(self.log_count)
        log_bar.addWidget(clear_log)
        log_page = QWidget()
        log_layout = QVBoxLayout(log_page)
        log_layout.addLayout(log_bar)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.document().setMaximumBlockCount(5000)
        self.log.setFont(QFont("Menlo", 11))
        self.log_highlighter = LogHighlighter(self.log.document())
        log_layout.addWidget(self.log, 1)
        self.output_tabs = QTabWidget()
        self.output_tabs.addTab(log_page, "Log")
        from crash_panel import CrashPanel
        def crash_context():
            device = self.device_log.currentData() or self.device.currentData() or {}
            return (self.info["root"] if self.info else "", self.bundle.text().strip(),
                    device.get("id", "") if isinstance(device, dict) and device.get("kind") == "simulator" else "")
        self.crash_panel = CrashPanel(crash_context)
        self.output_tabs.addTab(self.crash_panel, "Crash / Native")
        layout.addWidget(self.output_tabs, 1)
        self.log_timer = QTimer(self)
        self.log_timer.timeout.connect(self.flush_log)
        self.log_timer.start(100)
        self.live_timer = QTimer(self)
        self.live_timer.timeout.connect(self.poll_simulators)
        self.live_timer.start(5000)
        self.note = QLabel("Lần đầu: iPhone cần Trust This Computer, bật Developer Mode và mở khóa. "
                      "Apple ID/signing cần thiết lập một lần trong Xcode. Simulator không cần signing.")
        self.note.setWordWrap(True)
        layout.addWidget(self.note)
        self.setStyleSheet("""
          QMainWindow, QScrollArea, QWidget#content { background: #141c29; }
          QWidget { color: #e9eef7; font-size: 13px; }
          QTabWidget::pane { border: 1px solid #35455c; background: #141c29; }
          QTabBar::tab { background: #253041; color: #b8cee8; padding: 9px 26px; border: 1px solid #35455c; }
          QTabBar::tab:selected { background: #1d2a3c; color: #8cdda4; border-bottom: 2px solid #8cdda4; }
          QListWidget { background: #0e1623; border: 1px solid #35455c; border-radius: 6px; padding: 4px; }
          QListWidget::item { padding: 7px; }
          QListWidget::item:selected { background: #216cce; color: white; }
          QLabel#drop { border: 2px dashed #4b6683; border-radius: 12px; background: #1d2a3c; color: #b8cee8; }
          QGroupBox { border: 1px solid #35455c; border-radius: 9px; margin-top: 12px; padding: 17px 12px 10px; }
          QGroupBox::title { subcontrol-origin: margin; left: 12px; }
          QLineEdit, QComboBox, QPlainTextEdit { background: #0e1623; border: 1px solid #3c4c62; border-radius: 5px; padding: 6px; }
          QComboBox { padding-right: 32px; }
          QComboBox::drop-down { width: 25px; border-left: 1px solid #3c4c62; }
          QComboBox QAbstractItemView { padding: 5px; selection-background-color: #216cce; }
          QPushButton { background: #2b3c53; border: 1px solid #4a607c; border-radius: 6px; padding: 7px 13px; }
          QPushButton:hover { background: #38506e; }
          QPushButton:disabled { color: #7a8797; background: #253041; }
          QPushButton#primary { background: #216cce; border-color: #3683e8; font-weight: bold; }
          QPushButton#primary:disabled { background: #253041; border-color: #35455c; color: #7a8797; }
          QProgressBar { border: none; background: #26374c; } QProgressBar::chunk { background: #3d94ff; }
        """)
        arrow = (Path(__file__).parent / "arrow.svg").as_posix()
        self.setStyleSheet(self.styleSheet() +
                           f'QComboBox::down-arrow {{ image: url("{arrow}"); width: 12px; height: 8px; }}')
        threading.Thread(target=self.load_teams, daemon=True).start()
        last = self.settings.get("lastProject")
        if last and Path(last).is_dir():
            self.load_project(last)
        self.scan()
        self.update_run_availability()

    def append_log(self, text):
        self.pending_log.extend(re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", text).splitlines())

    def matches_log(self, line):
        lowered = line.lower()
        if self.log_filter.text().lower() not in lowered:
            return False
        level = self.log_level.currentData()
        if level == "error":
            return LogHighlighter.level(line) == "error"
        if level == "warning":
            return LogHighlighter.level(line) == "warning"
        return True

    def refresh_log_view(self):
        if not hasattr(self, "log"):
            return
        visible = [line for line in self.log_history if self.matches_log(line)]
        self.log.setPlainText("\n".join(visible))
        self.log.moveCursor(QTextCursor.MoveOperation.End)
        self.log_count.setText(f"{len(visible)}/{len(self.log_history)} dòng")

    def clear_log_view(self):
        self.pending_log.clear()
        self.log_history.clear()
        self.log.clear()
        self.log_count.setText("0 dòng")

    def flush_log(self):
        if not self.pending_log:
            return
        new_lines = list(self.pending_log)
        self.pending_log.clear()
        dropping = len(self.log_history) + len(new_lines) > self.log_history.maxlen
        self.log_history.extend(new_lines)
        filtered = bool(self.log_filter.text()) or self.log_level.currentData() != "all"
        if dropping and filtered:
            self.refresh_log_view()
        else:
            matching = [line for line in new_lines if self.matches_log(line)]
            if matching:
                self.log.appendPlainText("\n".join(matching))
                self.log.moveCursor(QTextCursor.MoveOperation.End)
            count = sum(1 for line in self.log_history if self.matches_log(line)) if filtered else len(self.log_history)
            self.log_count.setText(f"{count}/{len(self.log_history)} dòng")

    def status_update(self, text):
        self.status.setText(text)
        if text.startswith("App đang chạy"):
            if self.builder and self.builder.monitoring:
                self.project_list.setEnabled(True)
                self.mode.setEnabled(True)
                self.device.setEnabled(True)
                self.refresh.setEnabled(True)
                self.stop.setText("Ngắt log")
                self.update_run_availability()
                for index in range(self.device_log.count()):
                    device = self.device_log.itemData(index)
                    if device and device["id"] == self.builder.active_device_id:
                        self.device_log.blockSignals(True)
                        self.device_log.setCurrentIndex(index)
                        self.device_log.blockSignals(False)
                        break
            self.progress.setRange(0, 1)
            self.progress.setValue(1)

    def project_edited(self):
        if not self.info or self.project_path.text() != self.info["root"]:
            self.load_project(self.project_path.text())

    def refresh_projects(self):
        current = self.settings.get('lastProject') or (self.info["root"] if self.info else None)
        self.project_list.clear()
        for root, saved in self.settings["projects"].items():
            item = QListWidgetItem(saved.get("displayName") or Path(root).name)
            item.setData(Qt.ItemDataRole.UserRole, root)
            item.setToolTip(root)
            self.project_list.addItem(item)
            if root == current:
                self.project_list.setCurrentItem(item)

    def save_current_project(self, preserve_device=False):
        if not self.info or not self.config.currentData():
            return True
        root = self.info["root"]
        saved = self.settings["projects"].setdefault(root, {})
        device = self.device.currentData()
        saved.update(team=self.team.currentText().strip(), bundle=self.bundle.text().strip(),
                     creator=self.creator.text().strip(), kind=self.mode.currentData(),
                     device=device["id"] if device and not preserve_device else saved.get("device", ""),
                     config=self.config.currentData()["id"], reuseExisting=self.reuse_existing.isChecked())
        remember_options(self.settings, root, self.config.currentData()["id"], self.build_config.options())
        self.settings["lastProject"] = root
        try:
            self.settings_path.parent.mkdir(parents=True, exist_ok=True)
            self.settings_path.write_text(json.dumps(self.settings, indent=2))
            return True
        except OSError as error:
            self.status.setText("Không lưu được cấu hình: " + str(error))
            return False

    def reset_build_config(self):
        config = self.config.currentData()
        if config:
            self.build_config.load(config["options"])
            self.save_current_project()

    def rename_project(self):
        item = self.project_list.currentItem()
        if not item: return
        name, ok = QInputDialog.getText(self, "Tên hiển thị project", "Tên", text=item.text())
        if ok and name.strip():
            self.settings["projects"][item.data(Qt.ItemDataRole.UserRole)]["displayName"] = name.strip()
            self.settings_path.write_text(json.dumps(self.settings, indent=2))
            self.refresh_projects()

    def remove_project(self):
        if self.builder or self.sim_busy or self.checking_build or self.android_panel.busy:
            self.status.setText("Chờ tác vụ hoàn tất trước khi bỏ project khỏi danh sách.")
            return
        item = self.project_list.currentItem()
        if not item: return
        root = item.data(Qt.ItemDataRole.UserRole)
        if QMessageBox.question(self,"Bỏ project khỏi danh sách?",f"Bỏ {item.text()}? File dự án vẫn được giữ nguyên.") != QMessageBox.StandardButton.Yes:
            return
        self.settings["projects"].pop(root,None)
        if self.android_panel.info and self.android_panel.info['root'] == root:
            self.android_panel.info = None
            self.android_panel.task_id = None
            self.android_panel.config.clear()
            self.android_panel.project_label.setText('Chọn project trong danh sách bên trái để bắt đầu.')
            self.android_panel.update_actions()
        if self.settings.get("lastProject") == root:
            self.settings.pop("lastProject",None)
        if self.info and self.info["root"] == root:
            self.info = None
            self.project_path.clear()
            self.drop.setText("Kéo project Cocos vào đây")
            self.config.clear()
            self.build_config.load({})
            self.update_run_availability()
        self.settings_path.write_text(json.dumps(self.settings,indent=2))
        self.refresh_projects()

    def choose_project(self):
        folder = QFileDialog.getExistingDirectory(self, "Chọn project Cocos")
        if folder:
            self.load_project(folder)

    def choose_creator(self):
        path, _ = QFileDialog.getOpenFileName(self, "Chọn executable CocosCreator", "/Applications/Cocos/Creator")
        if path:
            self.creator.setText(path)
            self.check_tools()

    def load_project(self, folder):
        if self.android_panel.busy:
            self.android_panel.set_status('Dừng tác vụ Android trước khi đổi project.')
            return
        if self.sim_busy or self.checking_build or (self.builder and not self.builder.monitoring):
            self.status.setText("Đang build/thao tác thiết bị · Chờ hoàn tất để đổi project.")
            return
        if self.builder and self.builder.monitoring:
            self.pending_project = folder
            self.builder.cancel()
            return
        if self.info:
            self.save_current_project()
        android_valid = self.android_panel.load_project(folder)
        try:
            info = inspect_project(folder)
        except Exception as error:
            self.dependency_check_id += 1
            self.recheck_button.setEnabled(True)
            self.dependency_notice.setText("Chọn project hợp lệ để kiểm tra Cocos và Xcode.")
            self.dashboard_button.hide()
            self.xcode_button.hide()
            self.status.setText(str(error))
            self.info = None
            self.build_button.setEnabled(False)
            self.run_button.setEnabled(False)
            if hasattr(self, "clean_run_button"):
                self.clean_run_button.setEnabled(False)
            self.build_only_button.setEnabled(False)
            self.update_run_availability()
            if android_valid:
                self.platform_tabs.setCurrentIndex(1)
                self.android_panel.save()
                self.refresh_projects()
            return
        self.info = info
        self.settings["projects"].setdefault(info["root"], {})
        self.project_path.setText(info["root"])
        self.creator.setText(info["creator"])
        self.config.blockSignals(True)
        self.config.clear()
        for config in info["configs"]:
            self.config.addItem(config["label"], config)
        saved = self.settings["projects"].get(info["root"], {})
        for index in range(self.config.count()):
            if self.config.itemData(index)["id"] == saved.get("config"):
                self.config.setCurrentIndex(index)
        self.config.blockSignals(False)
        self.config_changed()
        if saved:
            self.team.setCurrentText(saved.get("team", self.team.currentText()))
            self.bundle.setText(saved.get("bundle", self.bundle.text()))
            self.creator.setText(saved.get("creator", info["creator"]))
            self.reuse_existing.setChecked(saved.get("reuseExisting", True))
            self.mode.setCurrentIndex(1 if saved.get("kind") == "simulator" else 0)
        elif info.get("suggestedBundle"):
            self.bundle.setText(info["suggestedBundle"])
        self.drop.setText(f'{Path(info["root"]).name}\nCocos Creator {info["version"]} · {len(info["configs"])} cấu hình iOS')
        self.check_tools()
        self.build_button.setEnabled(True)
        self.run_button.setEnabled(True)
        self.build_only_button.setEnabled(True)
        self.status.setText("Sẵn sàng · Bấm Build & Run" if saved or self.mode.currentData() == "simulator" else
                            "Sẵn sàng · kiểm tra Bundle ID và Team cho lần build đầu")
        if self.mode.currentData() == "simulator":
            self.scan()
        self.update_run_availability()
        self.save_current_project(preserve_device=True)
        self.refresh_projects()

    def config_changed(self):
        config = self.config.currentData()
        if not config:
            return
        edited = effective_options(self.settings, self.info["root"], config["id"], config["options"])
        self.build_config.load(edited, config["options"].get("scenes", []))
        ios = edited.get("packages", {}).get("ios", {})
        self.bundle.setText(ios.get("packageName", ""))
        desired_team = ios.get("developerTeam", "").split("_")[0]
        if self.team.count() == 1 and self.team.findText(desired_team) < 0:
            desired_team = self.team.itemText(0)
        self.team.setCurrentText(desired_team)

    def load_teams(self):
        try:
            self.events.teams.emit(scan_teams())
        except Exception as error:
            self.events.log.emit("Không đọc được signing team tự động: " + str(error))

    def teams_loaded(self, teams):
        value = self.team.currentText()
        for team, name in teams.items():
            self.team.addItem(team)
            self.team.setItemData(self.team.count() - 1, name, Qt.ItemDataRole.ToolTipRole)
        self.team.setCurrentText(next(iter(teams)) if len(teams) == 1 and value not in teams else value)

    def mode_changed(self):
        physical = self.mode.currentData() == "device"
        self.create_sim.setVisible(not physical)
        self.delete_sim.setVisible(not physical)
        self.update_simulator_buttons()
        self.team.setEnabled(physical)
        self.show_sim.setVisible(not physical)
        self.power_off_sim.setVisible(not physical)
        self.update_simulator_buttons()
        self.live.setText("" if physical else "Đang kiểm tra simulator đang bật…")
        self.note.setText("iPhone cần Trust This Computer, Developer Mode, mở khóa và signing đã thiết lập." if physical else
                          "Simulator không cần máy thật hay Apple signing. Tool tự chọn runtime tương thích với phiên bản Cocos.")
        if self.info:
            self.status.setText("Sẵn sàng · Bấm Build & Run để chạy trên " + ("iPhone" if physical else "simulator"))
        self.scan()
        if not physical:
            self.poll_simulators()

    def poll_simulators(self):
        if self.mode.currentData() != "simulator" or self.running_scan:
            return
        self.running_scan = True
        def work():
            try:
                devices = scan_simulators()
                for device in devices:
                    if device.get("state") == "Booted":
                        try:
                            device["activeApps"] = simulator_app_processes(device["id"])
                            device["activityKnown"] = True
                        except Exception:
                            device["activityKnown"] = False
                self.events.running.emit({"devices": devices})
            except Exception as error:
                self.events.running.emit({"error": str(error)})
        threading.Thread(target=work, daemon=True).start()

    def running_updated(self, result):
        self.running_scan = False
        if self.mode.currentData() != "simulator":
            return
        if result.get("error"):
            self.live.setText("Chưa đọc được trạng thái simulator · Bấm Refresh để thử lại")
            return
        states = {d["id"]: d for d in result["devices"]}
        for i in range(self.device.count()):
            device = self.device.itemData(i)
            if device and device.get("kind") == "simulator" and device["id"] in states:
                device = dict(device, **states[device["id"]])
                self.device.setItemData(i, device)
                self.device.setItemData(i, device["state"] == "Booted", BOOTED_ROLE)
        self.device.updateGeometry()
        self.device.update()
        self.sync_log_devices(result["devices"])
        self.booted_simulators = [d for d in result["devices"] if d.get("state") == "Booted"]
        names = [f'{d["name"]} ({d["runtime"]})' for d in self.booted_simulators]
        self.live.setText("Máy ảo đang bật: " + " · ".join(names) if names else "Chưa có máy ảo đang bật")
        selected = self.device.currentData()
        self.update_simulator_buttons()
        if selected:
            self.show_sim.setToolTip(f'Reload về idle · {selected["name"]} · Không tự chạy game')

    def sync_log_devices(self, devices):
        selected = self.device_log.currentData()
        selected_id = selected["id"] if selected else None
        self.device_log.blockSignals(True)
        self.device_log.clear()
        self.device_log.addItem("Chọn máy để xem log…", None)
        for device in devices:
            if device.get("kind") == "simulator" and device.get("state") == "Booted":
                self.device_log.addItem(f'{device["name"]} · {device.get("runtime", "")} · {device.get("state", "")}', device)
                if device["id"] == selected_id:
                    self.device_log.setCurrentIndex(self.device_log.count() - 1)
        self.device_log.blockSignals(False)

    def log_device_changed(self):
        device = self.device_log.currentData()
        if not device or not self.info or self.sim_busy or self.checking_build:
            return
        if self.builder:
            if not self.builder.monitoring:
                self.append_log("Đợi tác vụ build/run hoàn tất trước khi đổi Device log.")
                return
            if self.builder.active_device_id == device["id"]:
                return
            self.pending_log_device = dict(device)
            self.builder.cancel()
            return
        self.start_device_log(device)

    def start_device_log(self, device):
        worker = Builder(self.events.log.emit, self.events.stage.emit)
        self.builder = worker
        project, bundle = self.info["root"], self.bundle.text().strip()
        self.clear_log_view()
        self.stop.setEnabled(True)
        self.update_run_availability()
        def work():
            try:
                result = worker.observe(project, bundle, device)
                self.events.finished.emit(result, True)
            except Exception as error:
                self.events.finished.emit(str(error), False)
        threading.Thread(target=work, daemon=True).start()

    def show_simulator(self):
        selected = self.device.currentData()
        if self.sim_busy or not selected or selected.get("kind") != "simulator":
            return
        device_id = selected["id"]
        if self.builder and not self.builder.monitoring:
            # During compilation/install, only raise the viewer.
            def work():
                try:
                    capture(["/usr/bin/open", "-a", "Simulator", "--args", "-CurrentDeviceUDID", device_id])
                except Exception as error:
                    self.events.log.emit("Xem máy ảo: " + str(error))
            threading.Thread(target=work, daemon=True).start()
        else:
            self.run_simulator_action("boot", lambda: set_simulator_power(device_id, True))

    def restart_selected_simulator(self):
        selected = self.device.currentData()
        if (self.sim_busy or self.checking_build or not selected or selected.get("kind") != "simulator"
                or (self.builder and not self.builder.monitoring)):
            return
        device = dict(selected)
        reply = QMessageBox.question(self, "Khởi động lại máy ảo?",
            f'Khởi động lại "{device["name"]}" ({device.get("runtime", "")})?\n\nMáy sẽ tắt rồi bật lại. App đang chạy sẽ kết thúc; dữ liệu vẫn được giữ. Tool không tự mở lại game.',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if reply != QMessageBox.StandardButton.Yes:
            return
        self.pending_launch = None
        self.pending_log_device = None
        self.pending_shutdown_device = None
        if self.builder and self.builder.monitoring:
            self.pending_restart_device = device
            self.builder.cancel()
            return
        self.run_simulator_action("restart", lambda: restart_simulator(device["id"]))

    def shutdown_simulator(self):
        selected = self.device.currentData()
        if (self.sim_busy or self.checking_build or not selected or selected.get("kind") != "simulator"
                or (self.builder and not self.builder.monitoring)):
            return
        if selected.get("state") == "Shutdown":
            self.show_simulator()
            return
        if selected.get("state") != "Booted":
            return
        device = dict(selected)
        reply = QMessageBox.question(self, "Tắt máy ảo?",
            f'Tắt hẳn máy ảo "{device["name"]}" ({device.get("runtime", "")})?\n\nApp đang chạy trên máy này sẽ kết thúc. Các máy ảo khác không bị ảnh hưởng.',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if reply != QMessageBox.StandardButton.Yes:
            return
        if self.builder and self.builder.monitoring:
            self.pending_shutdown_device = device
            self.builder.cancel()
            return
        self.run_simulator_action("shutdown", lambda: set_simulator_power(device["id"], False, allow_running=True))

    def scan(self):
        kind = self.mode.currentData()
        selected = self.device.currentData()
        self.refresh_selected_simulator = selected.get("id") if selected else None
        self.refresh.setEnabled(False)
        self.device.clear()
        self.device.addItem("Đang tìm thiết bị…", None)
        self.update_run_availability()
        def work():
            try:
                devices = scan_simulators() if kind == "simulator" else scan_devices()
                self.events.scanned.emit({"kind": kind, "devices": devices}, "")
            except Exception as error:
                self.events.scanned.emit({"kind": kind, "devices": []}, str(error))
        threading.Thread(target=work, daemon=True).start()

    def scanned(self, result, error):
        if result["kind"] != self.mode.currentData():
            return
        self.refresh.setEnabled(True)
        self.device.clear()
        compatible = []
        for device in result["devices"]:
            extra = device.get("runtime") or ("USB" if device.get("transport") == "wired" else device.get("transport", ""))
            self.device.addItem(f'{device["name"]} · {extra}', device)
            self.device.setItemData(self.device.count() - 1,
                                    device.get("kind") == "simulator" and device.get("state") == "Booted",
                                    BOOTED_ROLE)
            supported = True
            if self.info and device.get("kind") == "simulator":
                old_engine = tuple(map(int, self.info["version"].split(".")[:2])) < (3, 8)
                arch = "x86_64" if old_engine else "arm64"
                supported = not device.get("architectures") or arch in device["architectures"]
            if supported:
                compatible.append(self.device.count() - 1)
            else:
                index = self.device.count() - 1
                self.device.setItemText(index, self.device.itemText(index) + " · chỉ quản lý")
                self.device.setItemData(index, f"Cocos {self.info['version']} cần {arch}; runtime này không hỗ trợ. Bạn vẫn có thể xóa máy ảo này.", Qt.ItemDataRole.ToolTipRole)
        if not result["devices"]:
            self.device.addItem("Chưa có máy ảo · bấm + Tạo máy ảo" if result["kind"] == "simulator" else
                                "Chưa có thiết bị · cắm USB / mở khóa rồi Refresh", None)
        if error:
            self.append_log("Refresh: " + error)
        if compatible:
            self.device.setCurrentIndex(compatible[0])
        if self.info:
            saved = self.settings["projects"].get(self.info["root"], {}).get("device")
            for i in range(self.device.count()):
                data = self.device.itemData(i)
                if data and data["id"] == saved and i in compatible:
                    self.device.setCurrentIndex(i)

        if result["kind"] == "simulator":
            running = [i for i in range(self.device.count()) if self.device.itemData(i) and self.device.itemData(i).get("state") == "Booted"]
            if running:
                preferred = getattr(self, "refresh_selected_simulator", None)
                choice = next((i for i in running if self.device.itemData(i)["id"] == preferred), running[0])
                self.device.setCurrentIndex(choice)

        if self.preferred_simulator:
            for i in range(self.device.count()):
                data = self.device.itemData(i)
                if data and data["id"] == self.preferred_simulator:
                    self.device.setCurrentIndex(i)
                    self.preferred_simulator = None
                    break
        self.update_simulator_buttons()

    def device_ready_to_run(self):
        selected = self.device.currentData()
        if not selected or not self.info:
            return False
        if self.mode.currentData() == "simulator":
            arch = "x86_64" if tuple(map(int, self.info["version"].split(".")[:2])) < (3, 8) else "arm64"
            return (selected.get("kind") == "simulator" and selected.get("state") in ("Booted", "Shutdown", "Booting")
                    and (not selected.get("architectures") or arch in selected["architectures"]))
        return selected.get("state", "").lower() == "connected" and selected.get("developerMode") == "enabled"

    def update_run_availability(self):
        if not hasattr(self, "build_only_button"):
            return
        ready = self.device_ready_to_run()
        enabled = bool(self.info) and (not self.builder or self.builder.monitoring) and not self.sim_busy and not self.checking_build
        self.build_only_button.setEnabled(enabled)
        self.build_button.setVisible(ready)
        self.build_button.setEnabled(enabled and ready)
        self.run_button.setEnabled(enabled and ready)
        self.clean_run_button.setEnabled(enabled and ready)
        self.run_notice.setVisible(not ready)
        if not self.info:
            self.run_notice.setText("Chọn project để kiểm tra thiết bị chạy app.")
        elif self.mode.currentData() == "simulator":
            self.run_notice.setText("Chưa có máy ảo phù hợp sẵn sàng để Run. Tạo/chọn máy ảo tương thích hoặc bấm làm mới. Bạn vẫn có thể Build trước.")
        else:
            self.run_notice.setText("Chưa có iPhone sẵn sàng để Run. Kết nối, mở khóa, Trust và bật Developer Mode rồi bấm làm mới. Bạn vẫn có thể Build trước.")

    def update_simulator_buttons(self):
        enabled = self.builder is None and not self.sim_busy and not self.checking_build
        self.create_sim.setEnabled(enabled)
        selected = self.device.currentData()
        has_simulator = bool(selected and selected.get("kind") == "simulator")
        protected = bool(has_simulator and selected.get("state") == "Booted" and
                         (not selected.get("activityKnown") or selected.get("activeApps")))
        self.delete_sim.setEnabled(enabled and has_simulator and not protected)
        self.delete_sim.setToolTip("Không xóa máy ảo khi app đang chạy hoặc chưa xác minh được trạng thái" if protected else "Xóa máy ảo đang chọn")
        if hasattr(self, "power_off_sim"):
            booted = has_simulator and selected.get("state") == "Booted"
            self.show_sim.setEnabled(not self.sim_busy and not self.checking_build and has_simulator and
                                     selected.get("state") in ("Booted", "Shutdown") and
                                     (not self.builder or self.builder.monitoring))
            power_enabled = (not self.sim_busy and not self.checking_build and has_simulator and
                             selected.get("state") in ("Booted", "Shutdown") and
                             (not self.builder or self.builder.monitoring))
            self.power_off_sim.setEnabled(power_enabled)
            label = "Tắt máy ảo đang chọn" if booted else "Bật máy ảo đang chọn"
            self.power_off_sim.setAccessibleName(label)
            self.power_off_sim.setToolTip(("Đang bật · Bấm để tắt: " if booted else "Đang tắt · Bấm để bật: ") +
                                          (selected["name"] if has_simulator else "chưa chọn máy"))
            background, border = ("#7f1d1d", "#ef4444") if booted else ("#166534", "#22c55e")
            self.power_off_sim.setStyleSheet(f"QPushButton {{ padding: 6px; background: {background}; border: 1px solid {border}; }} "
                                             "QPushButton:disabled { background: #253041; border-color: #4a607c; }")
            self.show_sim.setToolTip("Reload máy ảo về idle · Không tự chạy game")
        self.update_run_availability()

    def run_simulator_action(self, action, function):
        self.sim_busy = True
        self.update_simulator_buttons()
        self.build_button.setEnabled(False)
        self.run_button.setEnabled(False)
        if hasattr(self, "clean_run_button"):
            self.clean_run_button.setEnabled(False)
        self.build_only_button.setEnabled(False)
        self.project_list.setEnabled(False)
        self.controls.setEnabled(False)
        self.project_path.setEnabled(False)
        self.drop.setEnabled(False)
        self.mode.setEnabled(False)
        self.device.setEnabled(False)
        self.refresh.setEnabled(False)
        self.status.setText({"catalog": "Đang đọc mẫu iPhone và iOS runtime…", "create": "Đang tạo máy ảo…", "delete": "Đang xóa máy ảo…", "boot": "Đang mở máy ảo…", "shutdown": "Đang tắt máy ảo…", "restart": "Đang khởi động lại máy ảo…"}[action])
        def work():
            try:
                self.events.simulator_action.emit(dict(action=action, value=function()))
            except Exception as error:
                self.events.simulator_action.emit(dict(action=action, error=str(error)))
        threading.Thread(target=work, daemon=True).start()

    def new_simulator(self):
        if self.builder or self.sim_busy:
            return
        if not self.info:
            QMessageBox.information(self, "Chọn project", "Chọn project trước để tool lọc iOS tương thích với phiên bản Cocos.")
            return
        version = self.info["version"]
        self.run_simulator_action("catalog", lambda: simulator_catalog(version))

    def remove_simulator(self):
        selected = self.device.currentData()
        if self.builder or self.sim_busy or not selected or selected.get("kind") != "simulator":
            return
        reply = QMessageBox.warning(self, "Xóa máy ảo?",
            f'Xóa "{selected["name"]}" · {selected["runtime"]}?\nID: {selected["id"]}\n\nMáy sẽ được tắt nếu đang chạy. Toàn bộ app và dữ liệu trong máy ảo này sẽ bị xóa vĩnh viễn.',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            device_id = selected["id"]
            self.run_simulator_action("delete", lambda: delete_simulator(device_id))

    def simulator_action_done(self, result):
        self.sim_busy = False
        self.project_list.setEnabled(True)
        self.controls.setEnabled(True)
        self.project_path.setEnabled(True)
        self.drop.setEnabled(True)
        self.team.setEnabled(self.mode.currentData() == "device")
        self.mode.setEnabled(True)
        self.device.setEnabled(True)
        self.refresh.setEnabled(True)
        self.build_button.setEnabled(bool(self.info) and not self.builder)
        self.run_button.setEnabled(bool(self.info) and not self.builder)
        self.build_only_button.setEnabled(bool(self.info) and not self.builder)
        self.update_simulator_buttons()
        if result.get("error"):
            self.status.setText(result["error"])
            QMessageBox.warning(self, "Không thực hiện được", result["error"])
            return
        if result["action"] == "catalog":
            if not result["value"]:
                self.status.setText("Chưa có iOS runtime tương thích để tạo máy ảo.")
                QMessageBox.information(self, "Cần cài iOS runtime",
                    f'Chưa có iOS Simulator runtime tương thích với Cocos {self.info["version"]}.\nMở Xcode → Settings → Components / Platforms để cài iOS runtime. Cocos 3.7.x cần runtime hỗ trợ x86_64. Sau đó bấm Tạo máy ảo lại.')
                return
            dialog = CreateSimulatorDialog(result["value"], self)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                name, type_id = dialog.name.text(), dialog.model.currentData()
                runtime_id, version = dialog.runtime.currentData()["id"], self.info["version"]
                self.run_simulator_action("create", lambda: create_simulator(name, type_id, runtime_id, version))
            else:
                self.status.setText("Sẵn sàng · Bấm Build & Run")
        else:
            if result["action"] in ("create", "boot", "shutdown", "restart"):
                self.preferred_simulator = result["value"]
            self.status.setText({"create": "Đã tạo máy ảo · Bấm Build & Run", "delete": "Đã xóa máy ảo",
                                 "boot": "Máy ảo đã mở · Bấm Build & Run", "shutdown": "Đã tắt máy ảo", "restart": "Máy ảo ở idle · Bấm Run khi muốn chạy game"}[result["action"]])
            self.scan()
            self.poll_simulators()

    def open_dashboard(self):
        for path in (Path("/Applications/CocosDashboard.app"), Path("/Applications/Cocos/CocosDashboard.app")):
            if path.is_dir():
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
                return
        QDesktopServices.openUrl(QUrl("https://www.cocos.com/en/creator-download"))

    def check_tools(self, build_after=False):
        if not self.info or self.builder or self.sim_busy or self.checking_build:
            return
        self.dependency_check_id += 1
        token = self.dependency_check_id
        version, creator = self.info["version"], self.creator.text().strip()
        self.dependency_notice.setText(f"Đang kiểm tra Cocos Creator {version} và Xcode…")
        self.recheck_button.setEnabled(False)
        if build_after:
            self.checking_build = True
            self.project_list.setEnabled(False)
            self.controls.setEnabled(False)
            self.project_path.setEnabled(False)
            self.drop.setEnabled(False)
            self.mode.setEnabled(False)
            self.device.setEnabled(False)
            self.refresh.setEnabled(False)
            self.build_button.setEnabled(False)
            self.run_button.setEnabled(False)
            if hasattr(self, "clean_run_button"):
                self.clean_run_button.setEnabled(False)
            self.build_only_button.setEnabled(False)
            self.update_simulator_buttons()
        def work():
            try:
                issues = check_dependencies(version, creator)
            except Exception as error:
                issues = [{"code": "check", "message": "Không kiểm tra được công cụ: " + str(error)}]
            versions = installed_creator_versions(creator)
            self.events.dependencies.emit(dict(token=token, issues=issues, versions=versions, build_after=build_after))
        threading.Thread(target=work, daemon=True).start()

    def dependencies_updated(self, result):
        if result["token"] != self.dependency_check_id:
            return
        self.recheck_button.setEnabled(True)
        issues = result["issues"]
        installed = " · ".join(result.get("versions", [])) or "Chưa tìm thấy phiên bản Cocos nào"
        self.installed_cocos.setText(installed)
        self.installed_cocos.setToolTip(installed)
        self.installed_cocos.setCursorPosition(0)
        lines = []
        if any(i["code"] == "check" for i in issues):
            lines = ["⚠ " + i["message"] for i in issues]
        else:
            for code, ready in (("cocos", f'✓ Cocos Creator {self.info["version"]} đã sẵn sàng.'),
                                ("xcode", "✓ Xcode đã sẵn sàng.")):
                warnings = ["⚠ " + i["message"] for i in issues if i["code"] == code]
                lines.extend(warnings or [ready])
        self.dependency_notice.setText("\n\n".join(lines))
        self.dependency_notice.setStyleSheet("color: #ffd18a;" if issues else "color: #68dfa4;")
        self.dashboard_button.setVisible(any(i["code"] == "cocos" for i in issues))
        self.xcode_button.setVisible(any(i["code"] == "xcode" for i in issues))
        if result["build_after"]:
            self.checking_build = False
            self.project_list.setEnabled(True)
            self.controls.setEnabled(True)
            self.team.setEnabled(self.mode.currentData() == "device")
            self.project_path.setEnabled(True)
            self.drop.setEnabled(True)
            self.mode.setEnabled(True)
            self.device.setEnabled(True)
            self.refresh.setEnabled(True)
            self.build_button.setEnabled(True)
            self.run_button.setEnabled(True)
            self.build_only_button.setEnabled(True)
            blocking = [i for i in issues if i["code"] != "cocos" or not self.native_only.isChecked()]
            if blocking:
                self.advanced.setChecked(True)
                self.status.setText("Thiếu công cụ cần thiết · Xem cảnh báo phía trên.")
                QMessageBox.warning(self, "Chưa thể build iOS", "\n\n".join(i["message"] for i in blocking))
            else:
                self.begin_build(build_only=self.pending_build_only)
        self.update_simulator_buttons()

    def start_build(self, build_only=False):
        if self.android_panel.busy:
            self.status.setText('Dừng tác vụ Android trước khi build iOS.')
            return
        if self.builder and self.builder.monitoring:
            self.begin_build(build_only=build_only)
            return
        if self.info and not self.builder and not self.sim_busy and not self.checking_build:
            self.pending_build_only = build_only
            self.check_tools(build_after=True)

    def confirm_clean_run(self):
        if not self.device_ready_to_run() or self.sim_busy or self.checking_build or (self.builder and not self.builder.monitoring):
            return
        device = self.device.currentData()
        reply = QMessageBox.warning(self, "Clean & Run · Xóa app và dữ liệu?",
            f'Xóa {self.bundle.text().strip()} trên "{device["name"]}" và cài bản đã build mới nhất?\n\nGame đang chạy sẽ đóng. Dữ liệu app trên thiết bị này sẽ bị xóa. Không build lại.',
            QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Yes,
            QMessageBox.StandardButton.Cancel)
        if reply == QMessageBox.StandardButton.Yes:
            self.begin_build(run_only=True, clean=True)

    def begin_build(self, run_only=False, build_only=False, clean=False):
        if self.android_panel.busy:
            self.status.setText('Dừng tác vụ Android trước khi chạy iOS.')
            return
        if self.builder and self.builder.monitoring and not self.sim_busy:
            self.pending_launch = (run_only, build_only, clean)
            self.device.setEnabled(False)
            self.mode.setEnabled(False)
            self.refresh.setEnabled(False)
            self.status.setText("Đang chuyển phiên log · Giữ app cũ chạy độc lập")
            self.builder.cancel()
            return
        if not self.info or self.builder or self.sim_busy:
            return
        device = self.device.currentData()
        config = self.config.currentData()
        if not build_only and not self.device_ready_to_run():
            self.update_run_availability()
            self.status.setText("Chưa có thiết bị phù hợp sẵn sàng để Run.")
            return
        team, bundle = self.team.currentText().strip(), self.bundle.text().strip()
        creator = self.creator.text().strip()
        options = self.build_config.options()
        error = validate_options(options)
        if error:
            self.status.setText(error)
            QMessageBox.warning(self, "Cấu hình chưa hợp lệ", error)
            return
        if not self.save_current_project():
            return
        self.builder = Builder(self.events.log.emit, self.events.stage.emit)
        worker = self.builder
        self.project_list.setEnabled(False)
        self.controls.setEnabled(False)
        self.mode.setEnabled(False)
        self.device.setEnabled(False)
        self.refresh.setEnabled(False)
        self.project_path.setEnabled(False)
        self.drop.setEnabled(False)
        self.build_button.setEnabled(False)
        self.run_button.setEnabled(False)
        if hasattr(self, "clean_run_button"):
            self.clean_run_button.setEnabled(False)
        self.build_only_button.setEnabled(False)
        self.stop.setEnabled(True)
        self.update_simulator_buttons()
        self.progress.setRange(0, 0)
        self.clear_log_view()
        changed = options_changed(config["options"], options)
        args = (self.info["root"], options, creator, team, bundle, device,
                self.native_only.isChecked() and not changed, self.console.isChecked(),
                self.reuse_existing.isChecked(), self.force_export.isChecked())
        target_kind = self.mode.currentData()
        def work():
            try:
                if run_only:
                    app = worker.run_existing(self.info["root"], options, bundle, device,
                                              args[7], args[8], clean=clean)
                else:
                    app = worker.build(*args, build_only=build_only, target_kind=target_kind)
                self.events.finished.emit(app, True)
            except Exception as error:
                self.events.finished.emit(str(error), False)
        threading.Thread(target=work, daemon=True).start()

    def cancel(self):
        if self.builder:
            self.status.setText("Đang ngắt thu log · Không tắt game" if self.builder.monitoring else "Đang dừng tác vụ của tool…")
            self.builder.cancel()
            self.stop.setEnabled(False)

    def finished(self, result, success):
        self.builder = None
        self.project_list.setEnabled(True)
        self.controls.setEnabled(True)
        self.mode.setEnabled(True)
        self.device.setEnabled(True)
        self.refresh.setEnabled(True)
        self.team.setEnabled(self.mode.currentData() == "device")
        self.project_path.setEnabled(True)
        self.drop.setEnabled(True)
        self.build_button.setEnabled(True)
        self.run_button.setEnabled(True)
        self.build_only_button.setEnabled(True)
        self.stop.setEnabled(False)
        self.stop.setText("Dừng")
        self.update_simulator_buttons()
        self.progress.setRange(0, 1)
        self.progress.setValue(1 if success else 0)
        if success:
            self.append_log("Hoàn tất: " + result)
        else:
            self.status.setText(result)
            self.append_log("\n" + result)
        if self.pending_project:
            folder = self.pending_project
            self.pending_project = None
            self.load_project(folder)
        elif self.pending_restart_device:
            device = self.pending_restart_device
            self.pending_restart_device = None
            self.run_simulator_action("restart", lambda: restart_simulator(device["id"]))
        elif self.pending_shutdown_device:
            device = self.pending_shutdown_device
            self.pending_shutdown_device = None
            self.run_simulator_action("shutdown", lambda: set_simulator_power(device["id"], False, allow_running=True))
        elif self.pending_log_device:
            device = self.pending_log_device
            self.pending_log_device = None
            self.start_device_log(device)
        elif self.pending_launch:
            run_only, build_only, clean = self.pending_launch
            self.pending_launch = None
            self.begin_build(run_only=run_only, build_only=build_only, clean=clean)

    def closeEvent(self, event):
        if self.android_panel.busy:
            if QMessageBox.question(self, 'Dừng tác vụ Android?', 'Dừng tác vụ Android trước khi đóng tool?') == QMessageBox.StandardButton.Yes:
                self.android_panel.cancel()
            event.ignore()
            return
        self.android_panel.save()
        self.save_current_project()
        if self.sim_busy:
            QMessageBox.information(self, "Đang thao tác máy ảo", "Đợi thao tác máy ảo hoàn tất rồi đóng tool.")
            event.ignore()
            return
        if self.builder and self.builder.monitoring:
            self.builder.cancel()
            self.android_panel.stop_polling()
            event.accept()
            return
        if self.builder:
            reply = QMessageBox.question(self, "Dừng tác vụ?", "Dừng tác vụ của tool và đóng? Tool không kết thúc app trên simulator.")
            if reply != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self.builder.cancel()
        self.android_panel.stop_polling()
        event.accept()

    def refresh_platform_status(self):
        ios_busy = bool(self.builder and not self.builder.monitoring)
        android_busy = bool(self.android_panel.busy and not self.android_panel.runner.monitoring)
        for index, busy in enumerate((ios_busy, android_busy)):
            self.platform_badges[index].set_status(busy, self.platform_device_counts[index])
        self.platform_tick += 1
        if not self.isVisible() or self.platform_count_scanning or self.platform_tick % 25 != 1:
            return
        self.platform_count_scanning = True
        tools = self.android_panel.tools()
        def scan_counts():
            from android_backend import AndroidRunner
            result = {}
            try:
                sims = scan_simulators()
                phones = scan_devices()
                result[0] = sum(d.get('state') == 'Booted' for d in sims) + sum(d.get('state') == 'connected' for d in phones)
            except Exception: result[0] = None
            try:
                devices = AndroidRunner(tools, lambda _: None, lambda _: None).scan()
                result[1] = sum(d.get('state') == 'device' for d in devices)
            except Exception: result[1] = None
            self.events.platform_counts.emit(result)
        threading.Thread(target=scan_counts, daemon=True).start()

    def platform_counts_updated(self, result):
        self.platform_count_scanning = False
        for index in (0, 1):
            self.platform_device_counts[index] = result.get(index)

    def platform_changed(self, index):
        self.settings['platform'] = 'android' if index == 1 else 'ios'
        try:
            self.settings_path.parent.mkdir(parents=True, exist_ok=True)
            self.settings_path.write_text(json.dumps(self.settings, indent=2))
        except OSError as error:
            self.status.setText('Không lưu được tab: ' + str(error))


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(VERSION)
    app.setWindowIcon(QIcon(str(Path(__file__).parent / "app-icon.png")))
    app.setOrganizationName("Local Tools")
    window = Window()
    window.show()
    if len(sys.argv) > 1 and Path(sys.argv[1]).is_dir():
        window.load_project(sys.argv[1])
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
