"""Android desktop page: project profiles, local tools, devices, APK and Logcat."""
from __future__ import annotations

from collections import deque
import copy
import json
from pathlib import Path
import re
import threading

from PySide6.QtCore import QObject, Signal, QTimer, QUrl, Qt, QSize
from PySide6.QtGui import QDesktopServices, QFont, QTextCursor, QImage, QPixmap, QPainter, QColor, QIcon
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QGroupBox, QLabel, QLineEdit, QPushButton, QComboBox, QCheckBox, QPlainTextEdit,
    QFileDialog, QMessageBox, QInputDialog, QDialog, QDialogButtonBox, QProgressBar,
    QScrollArea, QFrame, QSizePolicy)

from backend import BuildError, export_folder
from android_backend import (AndroidRunner, AndroidDependencyError, AndroidDeviceError, discover_studios, default_sdk, sdk_inventory,
    sdk_tool, inspect_android_project, make_android_config, check_android_tools,
    strip_secrets, validate_android_options, java_major)
from build_config_panel import BuildConfigPanel
from log_style import LogHighlighter
from device_combo import BOOTED_ROLE, DeviceDelegate, ReadableComboBox, RefreshHint


class AndroidEvents(QObject):
    log = Signal(str)
    stage = Signal(str)
    done = Signal(object)
    inventory = Signal(object)
    java_home = Signal(str)
    logcat_done = Signal(object)


class AndroidPanel(QWidget):
    def __init__(self, host):
        super().__init__()
        self.setObjectName('content')
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.host = host
        self.info = None
        self.task_id = None
        self.loading = False
        self.runner = None
        self.log_runner = None
        self.log_target = None
        self.last_logcat_error = None
        self.callback = None
        self.last_apk = ''
        self.history = deque(maxlen=5000)
        self.pending = []
        self.dependency_issues = []
        self.last_dependency_report = None
        self.selected_targets = {}
        self.known_avds = {}
        self.pick_running_on_refresh = False
        self.poll_busy = False
        self.closing = False
        self.last_poll_error = None
        self.qr_dialog = None
        self.events = AndroidEvents(self)
        self.events.log.connect(self.append_log)
        self.events.stage.connect(self.set_status)
        self.events.done.connect(self.finished)
        self.events.inventory.connect(self.inventory_updated)
        self.events.java_home.connect(self.apply_java_home)
        self.events.logcat_done.connect(self.logcat_finished)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        title = QLabel('ANDROID · APK BUILDER')
        title.setStyleSheet('font-size: 22px; font-weight: bold; color: #8cdda4;')
        layout.addWidget(title)
        subtitle = QLabel('Cocos Creator → Gradle → APK → Máy ảo / điện thoại Android')
        subtitle.setWordWrap(True); layout.addWidget(subtitle)
        self.project_label = QLabel('Chọn project trong danh sách bên trái để bắt đầu.')
        self.project_label.setWordWrap(True); layout.addWidget(self.project_label)
        self.controls = QWidget()
        content = QVBoxLayout(self.controls); content.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.controls)
        self.setup_tools(content)
        config_group = QGroupBox('Cấu hình Cocos Android')
        form = QVBoxLayout(config_group)
        row = QHBoxLayout()
        self.config = QComboBox(); self.config.setMinimumContentsLength(20)
        self.config.currentIndexChanged.connect(self.config_changed)
        row.addWidget(self.config, 1)
        self.cocos_button = QPushButton('Mở Cocos Creator')
        self.cocos_button.clicked.connect(self.open_cocos); row.addWidget(self.cocos_button)
        form.addLayout(row)
        self.config_notice = QLabel('Chưa chọn project.'); self.config_notice.setWordWrap(True)
        form.addWidget(self.config_notice)
        self.build_config = BuildConfigPanel(platform='android')
        self.build_config.changed.connect(self.save)
        self.build_config.reset_requested.connect(self.reset_config)
        form.addWidget(self.build_config)
        self.native_only = QCheckBox('Chỉ build Gradle từ bản export hiện tại')
        self.native_only.setToolTip('Chỉ dùng khi asset/script/cấu hình không đổi; bình thường nên để tắt.')
        form.addWidget(self.native_only)
        content.addWidget(config_group)
        self.setup_devices(content)
        self.setup_build_actions(content)
        state = QHBoxLayout()
        self.status = QLabel('Chọn project Android để bắt đầu.'); self.status.setWordWrap(True)
        state.addWidget(self.status, 1)
        self.stop = QPushButton('Dừng'); self.stop.setEnabled(False)
        self.stop.clicked.connect(self.cancel); state.addWidget(self.stop)
        layout.addLayout(state)
        self.progress = QProgressBar(); self.progress.setRange(0, 1); self.progress.setValue(0)
        self.progress.setMaximumHeight(5); self.progress.setTextVisible(False); layout.addWidget(self.progress)
        log_bar = QHBoxLayout()
        self.log_filter = QLineEdit(); self.log_filter.setPlaceholderText('Tìm trong log Android…')
        self.log_filter.textChanged.connect(self.refresh_log)
        log_bar.addWidget(self.log_filter, 1)
        self.log_level = QComboBox()
        for name, value in (('Tất cả', 'all'), ('Error', 'error'), ('Warning', 'warning')): self.log_level.addItem(name, value)
        self.log_level.currentIndexChanged.connect(self.refresh_log); log_bar.addWidget(self.log_level)
        clear = QPushButton('Clear log'); clear.clicked.connect(self.clear_log); log_bar.addWidget(clear)
        layout.addLayout(log_bar)
        self.log = QPlainTextEdit(); self.log.setReadOnly(True)
        self.log.setFont(QFont('Menlo', 11)); self.log.setMinimumHeight(210)
        self.log.document().setMaximumBlockCount(5000)
        self.highlighter = LogHighlighter(self.log.document()); layout.addWidget(self.log, 1)
        note = QLabel('USB: bật Developer options → USB debugging và xác nhận RSA trên điện thoại. Wi-Fi: điện thoại và Mac cùng mạng; dùng cổng Pair và Connect riêng trong Wireless debugging.')
        note.setWordWrap(True); layout.addWidget(note)
        self.timer = QTimer(self); self.timer.timeout.connect(self.flush_log); self.timer.start(100)
        self.refresh_studios()
        self.update_actions()
        self.device_timer = QTimer(self)
        self.device_timer.timeout.connect(self.poll_devices)
        self.device_timer.start(3000)

    @property
    def busy(self):
        return self.runner is not None

    def button(self, text, action, row):
        button = QPushButton(text.replace('&', '&&')); button.clicked.connect(action); row.addWidget(button)
        return button

    def setup_tools(self, layout):
        self.tools_toggle = QPushButton('Công cụ Android · Studio / SDK / NDK / JDK ▸')
        self.tools_toggle.setCheckable(True)
        layout.addWidget(self.tools_toggle)
        self.tools_summary = QLabel(''); self.tools_summary.setWordWrap(True); layout.addWidget(self.tools_summary)
        self.dependency_notice = QFrame()
        self.dependency_notice.setObjectName('dependencyNotice')
        self.dependency_notice.setStyleSheet('QFrame#dependencyNotice { background: #302719; border: 1px solid #8f713d; border-radius: 7px; } QLabel { color: #ffd166; }')
        notice_layout = QVBoxLayout(self.dependency_notice)
        notice_layout.addWidget(QLabel('⚠ Cần bổ sung công cụ Android'))
        self.dependency_message = QLabel(); self.dependency_message.setWordWrap(True)
        notice_layout.addWidget(self.dependency_message)
        notice_buttons = QHBoxLayout()
        self.notice_instructions = self.button('Hướng dẫn cài đặt…', self.show_dependency_notification, notice_buttons)
        self.notice_studio = self.button('Mở Android Studio', self.open_studio, notice_buttons)
        self.notice_download_studio = self.button('Tải Android Studio', lambda: self.open_url('https://developer.android.com/studio'), notice_buttons)
        self.notice_download_cocos = self.button('Tải Cocos Creator', lambda: self.open_url('https://www.cocos.com/en/creator-download'), notice_buttons)
        notice_layout.addLayout(notice_buttons)
        layout.addWidget(self.dependency_notice)
        self.dependency_notice.hide()
        group = QGroupBox('Công cụ Android'); form = QFormLayout(group)
        self.tools_toggle.toggled.connect(group.setVisible)
        self.tools_toggle.toggled.connect(lambda opened: self.tools_toggle.setText('Công cụ Android · Studio / SDK / NDK / JDK ' + ('▾' if opened else '▸')))
        self.studio = QComboBox(); self.studio.setMinimumContentsLength(25)
        self.studio.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.studio.currentIndexChanged.connect(self.studio_changed)
        row = QHBoxLayout(); row.addWidget(self.studio, 1)
        self.button('Chọn .app…', self.choose_studio, row)
        self.button('Quét lại', self.refresh_studios, row)
        self.button('Mở Studio', self.open_studio, row)
        form.addRow('Android Studio', row)
        self.paths = {}
        for key, label in (('sdk', 'Android SDK'), ('ndk', 'Android NDK'), ('java', 'Java Home / JDK'), ('creator', 'Cocos Creator')):
            field = QLineEdit(); self.paths[key] = field
            field.editingFinished.connect(self.tools_edited)
            row = QHBoxLayout(); row.addWidget(field, 1)
            self.button('Chọn…', lambda checked=False, k=key: self.choose_path(k), row)
            form.addRow(label, row)
        self.ndk_versions = QComboBox()
        self.ndk_versions.currentIndexChanged.connect(self.ndk_changed)
        form.addRow('NDK đã cài', self.ndk_versions)
        self.java_versions = QComboBox()
        self.java_versions.currentIndexChanged.connect(self.java_changed)
        form.addRow('JDK đã cài', self.java_versions)
        self.inventory_label = QLabel(''); self.inventory_label.setWordWrap(True)
        form.addRow(self.inventory_label)
        row = QHBoxLayout()
        self.button('Kiểm tra công cụ', self.check_tools, row)
        self.button('Mở Studio (SDK / AVD)', self.open_studio, row)
        self.button('Tải Android Studio', lambda: self.open_url('https://developer.android.com/studio'), row)
        self.button('Tải Cocos', lambda: self.open_url('https://www.cocos.com/en/creator-download'), row)
        form.addRow(row)
        self.tool_notice = QLabel('Chọn project rồi kiểm tra bộ công cụ Android.'); self.tool_notice.setWordWrap(True)
        form.addRow(self.tool_notice); layout.addWidget(group)
        group.hide()

    def setup_devices(self, layout):
        group = QGroupBox('Thiết bị Android'); form = QVBoxLayout(group)
        row = QHBoxLayout()
        self.mode = QComboBox(); self.mode.addItem('Máy ảo Android', 'emulator'); self.mode.addItem('Điện thoại thật', 'device')
        self.mode.currentIndexChanged.connect(self.mode_changed)
        row.addWidget(self.mode)
        self.device = ReadableComboBox(); self.device.setMinimumContentsLength(25)
        self.device.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.device.setItemDelegate(DeviceDelegate(self.device))
        self.device.currentIndexChanged.connect(self.target_changed); row.addWidget(self.device, 1)
        self.refresh_button = self.button('Refresh', self.scan_devices, row)
        self.refresh_hint = RefreshHint(self.refresh_button, lambda: self.mode.currentData() == 'emulator' and not self.device.currentData() and not self.busy)
        self.device.currentIndexChanged.connect(self.refresh_hint.sync)
        self.mode.currentIndexChanged.connect(self.refresh_hint.sync)
        form.addLayout(row)
        self.emulator_controls = QWidget()
        row = QHBoxLayout(self.emulator_controls); row.setContentsMargins(0,0,0,0)
        self.button('＋ Tạo AVD', self.prepare_create_avd, row)
        self.button('Mở AVD đã chọn', self.start_avd, row)
        for icon, label, action in (('power', 'Bật/tắt máy ảo đang chọn', self.toggle_avd_power), ('delete', 'Xóa máy ảo đang chọn', self.delete_avd)):
            button = self.button('', action, row)
            button.setIcon(QIcon(str(Path(__file__).parent / f'icon-{icon}.svg')))
            button.setIconSize(QSize(18, 18))
            button.setFixedSize(34, 34)
            button.setStyleSheet('padding: 6px;')
            button.setToolTip(label)
            button.setAccessibleName(label)
            if icon == 'power': self.power_avd_button = button
        form.addWidget(self.emulator_controls)
        self.physical_controls = QWidget()
        physical = QVBoxLayout(self.physical_controls); physical.setContentsMargins(0,0,0,0)
        row = QHBoxLayout()
        self.button('Kết nối USB / Quét lại', self.scan_devices, row)
        self.qr_button = self.button('Kết nối Wi-Fi bằng QR…', self.pair_qr_code, row)
        physical.addLayout(row)
        row = QHBoxLayout()
        self.address = QLineEdit(); self.address.setPlaceholderText('Wi-Fi host:port từ Wireless debugging trên điện thoại')
        row.addWidget(self.address, 1)
        self.button('Pair bằng mã…', self.pair_wireless, row)
        self.button('Connect Wi-Fi', self.connect_wireless, row)
        physical.addLayout(row)
        form.addWidget(self.physical_controls)
        self.physical_controls.hide()
        self.device_notice = QLabel('Chọn thiết bị để điều khiển. Danh sách tự cập nhật trạng thái mỗi 3 giây.')
        self.device_notice.setWordWrap(True); form.addWidget(self.device_notice)
        self.devices = []; layout.addWidget(group)
        self.filter_devices()

    def setup_build_actions(self, layout):
        row = QHBoxLayout()
        self.build_button = self.button('Build APK', lambda: self.start_build(False), row)
        self.build_run_button = self.button('Build & Run', lambda: self.start_build(True), row)
        self.build_run_button.setObjectName('primary')
        self.run_button = self.button('Run APK đã build', lambda: self.run_apk(False), row)
        self.clean_button = self.button('Clean & Run…', lambda: self.run_apk(True), row)
        layout.addLayout(row)
        row = QHBoxLayout()
        self.apk = QLineEdit(); self.apk.setReadOnly(True); self.apk.setPlaceholderText('APK của lần build thành công hoặc APK chọn thủ công')
        row.addWidget(self.apk, 1)
        self.button('Chọn APK…', self.choose_apk, row)
        layout.addLayout(row)

    def open_url(self, url):
        QDesktopServices.openUrl(QUrl(url))

    def tools(self):
        data = {k: field.text().strip() for k, field in self.paths.items()}
        selected = self.studio.currentData()
        data['studio'] = selected['path'] if selected else ''
        return data

    def refresh_studios(self):
        if self.busy: return
        previous = self.studio.currentData()
        previous = previous['path'] if previous else ''
        studios = discover_studios()
        self.loading = True
        self.studio.clear()
        for studio in studios:
            self.studio.addItem(f'{studio["version"]} · {studio["path"]}', studio)
        if previous:
            for i in range(self.studio.count()):
                if self.studio.itemData(i)['path'] == previous: self.studio.setCurrentIndex(i)
        self.loading = False
        self.paths['sdk'].setText(self.paths['sdk'].text() or default_sdk())
        self.refresh_inventory()
        if not self.paths['java'].text(): self.studio_changed()

    def refresh_inventory(self):
        inventory = sdk_inventory(self.paths['sdk'].text())
        previous = self.paths['ndk'].text()
        self.ndk_versions.blockSignals(True); self.ndk_versions.clear()
        for path in inventory['ndk']: self.ndk_versions.addItem(Path(path).name, path)
        index = self.ndk_versions.findData(previous)
        self.ndk_versions.setCurrentIndex(max(index, 0)); self.ndk_versions.blockSignals(False)
        if not previous and inventory['ndk']:
            chosen = next((p for p in inventory['ndk'] if Path(p).name.startswith('23.')), inventory['ndk'][0]) if self.info and self.info['version'].startswith('3.7.') else inventory['ndk'][0]
            self.paths['ndk'].setText(chosen)
            self.ndk_versions.setCurrentIndex(self.ndk_versions.findData(chosen))
        self.java_versions.blockSignals(True); self.java_versions.clear()
        candidates = {s['java'] for s in discover_studios() if s['java']}
        for folder in (Path('/Library/Java/JavaVirtualMachines'), Path.home() / 'Library/Java/JavaVirtualMachines'):
            candidates.update(str(p) for p in folder.glob('*/Contents/Home') if (p / 'bin/java').is_file())
        for java in sorted(candidates): self.java_versions.addItem(f'JDK {java_major(java) or "?"} · {java}', java)
        self.java_versions.setCurrentIndex(self.java_versions.findData(self.paths['java'].text()))
        self.java_versions.blockSignals(False)
        platforms = ', '.join(Path(p).name for p in inventory['platforms']) or 'chưa cài'
        builds = ', '.join(Path(p).name for p in inventory['build-tools']) or 'chưa cài'
        self.inventory_label.setText(f'SDK Platform: {platforms}\nBuild Tools: {builds}')
        studio = self.studio.currentData()
        self.tools_summary.setText(f'Studio {studio["version"] if studio else "chưa chọn"} · JDK {java_major(self.paths["java"].text()) or "?"} · NDK {Path(self.paths["ndk"].text()).name or "chưa chọn"}')

    def studio_changed(self):
        if self.loading: return
        studio = self.studio.currentData()
        if studio and studio.get('java'): self.paths['java'].setText(studio['java'])
        self.refresh_inventory(); self.save(); self.auto_check_tools()

    def ndk_changed(self):
        if not self.loading and self.ndk_versions.currentData():
            self.paths['ndk'].setText(self.ndk_versions.currentData()); self.save(); self.auto_check_tools()

    def java_changed(self):
        if not self.loading and self.java_versions.currentData():
            self.paths['java'].setText(self.java_versions.currentData()); self.save(); self.auto_check_tools()

    def tools_edited(self):
        self.refresh_inventory(); self.save(); self.auto_check_tools()

    def choose_studio(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Chọn Android Studio.app', '/Applications', 'Applications (*.app)')
        if not path: return
        studios = discover_studios([Path(path).parent])
        selected = next((s for s in studios if s['path'] == path), None)
        if not selected:
            QMessageBox.warning(self, 'Android Studio', 'Chọn application bundle Android Studio hợp lệ.'); return
        index = next((i for i in range(self.studio.count()) if self.studio.itemData(i)['path'] == path), -1)
        if index < 0: self.studio.addItem(f'{selected["version"]} · {path}', selected); index = self.studio.count() - 1
        self.studio.setCurrentIndex(index)

    def choose_path(self, key):
        if key == 'creator':
            path, _ = QFileDialog.getOpenFileName(self, 'Chọn executable CocosCreator', '/Applications/Cocos/Creator')
        else:
            path = QFileDialog.getExistingDirectory(self, 'Chọn ' + key.upper(), self.paths[key].text())
        if path: self.paths[key].setText(path); self.tools_edited()

    def open_studio(self):
        selected = self.studio.currentData()
        if selected: QDesktopServices.openUrl(QUrl.fromLocalFile(selected['path']))
        else: self.open_url('https://developer.android.com/studio')

    def open_cocos(self):
        path = self.paths['creator'].text()
        if not Path(path).is_file(): self.open_url('https://www.cocos.com/en/creator-download'); return
        root = self.info['root'] if self.info else ''
        self.task('Mở Cocos', lambda runner: runner.run(['/usr/bin/open', '-a', str(Path(path).parents[2]), '--args', '--path', root], timeout=20))

    def load_project(self, folder):
        if self.busy: return False
        self.stop_auto_logcat()
        self.save()
        self.loading = True
        try:
            self.info = inspect_android_project(folder)
        except Exception as error:
            self.info = None; self.project_label.setText(str(error)); self.loading = False; self.update_actions(); return False
        root = self.info['root']
        saved = self.host.settings.setdefault('projects', {}).setdefault(root, {}).get('android', {})
        tools = dict(saved.get('tools', self.host.settings.get('androidTools', {})))
        if not saved.get('tools'):
            tools['creator'] = self.info['creator']
        self.config.clear(); self.task_id = None
        for config in self.info['configs']: self.config.addItem(config['label'], config)
        for index in range(self.config.count()):
            if self.config.itemData(index)['id'] == saved.get('task'): self.config.setCurrentIndex(index)
        for key, field in self.paths.items(): field.setText(tools.get(key, self.info['creator'] if key == 'creator' else default_sdk() if key == 'sdk' else ''))
        studios = [self.studio.itemData(i) for i in range(self.studio.count())]
        studio_path = tools.get('studio', '')
        chosen = next((i for i,s in enumerate(studios) if s['path'] == studio_path), -1)
        if chosen < 0 and self.info['version'].startswith(('3.6.', '3.7.')):
            chosen = next((i for i,s in enumerate(studios) if java_major(s.get('java', '')) == 11), -1)
        if chosen >= 0: self.studio.setCurrentIndex(chosen)
        if not self.paths['java'].text() and self.studio.currentData(): self.paths['java'].setText(self.studio.currentData().get('java', ''))
        self.refresh_inventory()
        self.project_label.setText(f'{Path(root).name} · Cocos {self.info["version"]}\n{root}')
        self.selected_targets = dict(saved.get('targets', {}))
        self.device.blockSignals(True); self.device.clear(); self.device.blockSignals(False)
        self.mode.setCurrentIndex(1 if saved.get('mode') == 'device' else 0)
        self.last_apk = saved.get('apk', '')
        self.manual_apk = saved.get('manualApk', False)
        self.apk.setText(self.last_apk)
        self.devices = []; self.filter_devices()
        self.loading = False
        self.config_changed()
        self.update_actions()
        self.set_status('Sẵn sàng · Kiểm tra công cụ hoặc Build APK.' if self.info['configs'] else 'Tạo task Android trong Cocos rồi chọn lại project.')
        self.auto_check_tools()
        return True

    def config_changed(self):
        if self.loading: return
        self.save()
        task = self.config.currentData()
        self.task_id = task['id'] if task else None
        self.loading = True
        if task and self.info:
            saved = self.host.settings['projects'][self.info['root']].get('android', {})
            options = copy.deepcopy(saved.get('buildOptions', {}).get(task['id'], task['options']))
            android = options.setdefault('packages', {}).setdefault('android', {})
            android.setdefault('orientation', {'portrait': True, 'upsideDown': False, 'landscapeLeft': False, 'landscapeRight': False})
            self.build_config.load(options)
            self.config_notice.setText('Cấu hình được lưu riêng trong tool. Mặc định build Debug APK để cài và chạy thử.')
        else:
            self.build_config.load({})
            self.config_notice.setText('Chưa có task Android. Mở Cocos → Project → Build → Android, tạo và lưu task; sau đó chọn lại project.')
        self.build_config.setEnabled(bool(task))
        self.loading = False
        self.native_only.setChecked(False)
        self.update_actions()

    def reset_config(self):
        task = self.config.currentData()
        if task:
            self.build_config.load(task['options']); self.save()

    def save(self, *args):
        if self.loading or not self.info: return
        root = self.info['root']
        saved = self.host.settings['projects'].setdefault(root, {}).setdefault('android', {})
        if self.task_id:
            saved.setdefault('buildOptions', {})[self.task_id] = strip_secrets(self.build_config.options())
        saved.update(task=self.task_id, tools=self.tools(), mode=self.mode.currentData(), targets=dict(self.selected_targets), apk=self.last_apk, manualApk=getattr(self, 'manual_apk', False))
        self.host.settings['androidTools'] = self.tools()
        self.host.settings['lastProject'] = root
        try:
            self.host.settings_path.parent.mkdir(parents=True, exist_ok=True)
            self.host.settings_path.write_text(json.dumps(self.host.settings, indent=2))
        except OSError as error:
            self.set_status('Error: Không lưu được cấu hình Android: ' + str(error))

    def set_status(self, text):
        self.status.setText(text)

    def task(self, name, work, callback=None):
        if self.busy: return
        if (self.host.builder and not self.host.builder.monitoring) or self.host.sim_busy or self.host.checking_build:
            self.warn_user('Đang có tác vụ iOS', 'Chờ tác vụ iOS hoàn tất trước khi chạy Android.'); return
        self.save()
        self.runner = AndroidRunner(self.tools(), self.events.log.emit, self.events.stage.emit, java_selected=self.events.java_home.emit)
        self.callback = callback
        self.controls.setEnabled(False); self.stop.setEnabled(True)
        self.progress.setRange(0, 0); self.set_status(name + '…')
        runner = self.runner
        def execute():
            try: value = work(runner); result = {'ok': True, 'value': value, 'name': name}
            except AndroidDeviceError as error:
                result = {'ok': False, 'error': str(error), 'name': name, 'device_error': True}
            except AndroidDependencyError as error:
                result = {'ok': False, 'error': str(error), 'name': name, 'dependencies': error.issues}
            except Exception as error:
                result = {'ok': False, 'error': str(error), 'name': name, 'cancelled': runner.cancelled.is_set()}
            self.events.done.emit(result)
        self.thread = threading.Thread(target=execute, daemon=True); self.thread.start()

    def finished(self, result):
        self.runner = None
        self.controls.setEnabled(True); self.stop.setEnabled(False)
        self.progress.setRange(0, 1); self.progress.setValue(1 if result['ok'] else 0)
        callback, self.callback = self.callback, None
        if self.qr_dialog is not None:
            self.qr_dialog.accept() if result['ok'] else self.qr_dialog.reject()
        if result['ok']:
            self.set_status(result['name'] + ' · Hoàn tất')
            if callback: callback(result['value'])
        else:
            self.append_log('\n'.join('Error: ' + line for line in result['error'].splitlines()))
            self.set_status(result['error'])
            if result.get('dependencies'):
                self.tools_checked(result['dependencies'], repeat=False)
                self.show_dependency_notification()
            elif result.get('device_error'):
                QMessageBox.warning(self, 'Thiết bị Android chưa sẵn sàng', result['error'])
            elif not result.get('cancelled'):
                QMessageBox.warning(self, 'Không thể hoàn tất tác vụ Android', result['error'])
        self.update_actions()

    def cancel(self):
        if self.runner:
            self.runner.cancel(); self.set_status('Đang dừng tác vụ Android…'); self.stop.setEnabled(False)

    def update_actions(self, *args):
        valid = bool(self.info and self.config.currentData())
        ready = bool(self.device.currentData() and self.device.currentData().get('state') == 'device')
        self.build_button.setEnabled(valid)
        self.build_run_button.setEnabled(not self.busy)
        self.run_button.setEnabled(bool(self.info) and ready)
        self.clean_button.setEnabled(bool(self.info) and ready)
        self.update_power_button()

    def update_power_button(self):
        if not hasattr(self, 'power_avd_button'): return
        target = self.device.currentData()
        is_avd = bool(target and target.get('kind') == 'emulator' and target.get('avd'))
        running = bool(is_avd and target.get('state') == 'device' and target.get('serial'))
        ready = is_avd and target.get('state') in ('stopped', 'device')
        self.power_avd_button.setEnabled(bool(ready and not self.busy))
        label = 'Tắt máy ảo đang chọn' if running else 'Bật máy ảo đang chọn'
        self.power_avd_button.setAccessibleName(label)
        self.power_avd_button.setToolTip(('Đang bật · Bấm để tắt: ' if running else 'Đang tắt · Bấm để bật: ') + (target['name'] if is_avd else 'chưa chọn máy'))
        background, border = ('#7f1d1d', '#ef4444') if running else ('#166534', '#22c55e')
        self.power_avd_button.setStyleSheet(f'QPushButton {{ padding: 6px; background: {background}; border: 1px solid {border}; }} '
                                          'QPushButton:disabled { background: #253041; border-color: #4a607c; }')

    def toggle_avd_power(self):
        target = self.device.currentData()
        if target and target.get('state') == 'stopped':
            self.start_avd()
        elif target and target.get('state') == 'device':
            self.stop_avd()

    def check_tools(self):
        version = self.info['version'] if self.info else ''
        self.task('Kiểm tra công cụ', lambda runner: check_android_tools(runner.tools, version, build=bool(version), include_avd=True), self.tools_checked)

    def auto_check_tools(self):
        if not self.loading and self.info:
            self.tools_checked(check_android_tools(self.tools(), self.info['version'], include_avd=True), repeat=False)

    def tools_checked(self, issues, repeat=True):
        self.dependency_issues = list(issues)
        text = '\n'.join('Warning: ' + i for i in issues) if issues else '✓ Công cụ Android đã tìm thấy. Khi build sẽ kiểm tra thêm Gradle/JDK.'
        self.tool_notice.setText(text)
        self.tool_notice.setStyleSheet('color: #ffd166;' if issues else 'color: #8cdda4;')
        self.dependency_message.setText('\n'.join('• ' + i for i in issues))
        self.dependency_notice.setVisible(bool(issues))
        cocos_missing = any('Cocos Creator' in i for i in issues)
        android_missing = any('Cocos Creator' not in i for i in issues)
        self.notice_studio.setVisible(android_missing)
        self.notice_download_studio.setVisible(android_missing and not self.studio.currentData())
        self.notice_download_cocos.setVisible(cocos_missing)
        report = (self.info['root'] if self.info else '', tuple(issues))
        if repeat or report != self.last_dependency_report:
            self.append_log(text)
        self.last_dependency_report = report

    def show_dependency_notification(self, checked=False):
        if not self.dependency_issues: return
        dialog = QMessageBox(self)
        dialog.setWindowTitle('Thiếu công cụ Android · Hướng dẫn cài đặt')
        dialog.setIcon(QMessageBox.Icon.Warning)
        dialog.setText('Cần cài hoặc chọn các công cụ sau để tiếp tục:')
        dialog.setInformativeText('\n\n'.join(self.dependency_issues))
        studio_button = cocos_button = None
        if any('Cocos Creator' not in i for i in self.dependency_issues):
            studio_button = dialog.addButton('Mở Android Studio', QMessageBox.ButtonRole.ActionRole)
        if any('Cocos Creator' in i for i in self.dependency_issues):
            cocos_button = dialog.addButton('Tải Cocos Creator', QMessageBox.ButtonRole.ActionRole)
        dialog.addButton(QMessageBox.StandardButton.Close)
        dialog.exec()
        if studio_button and dialog.clickedButton() == studio_button: self.open_studio()
        elif cocos_button and dialog.clickedButton() == cocos_button: self.open_url('https://www.cocos.com/en/creator-download')

    def apply_java_home(self, home):
        self.paths['java'].setText(home)
        self.refresh_inventory(); self.save(); self.auto_check_tools()

    def poll_devices(self, force=False):
        if self.closing or self.poll_busy or self.busy: return
        if not force and not self.isVisible(): return
        if self.host.sim_busy or self.host.checking_build or (self.host.builder and not self.host.builder.monitoring): return
        tools = self.tools(); known = dict(self.known_avds)
        self.poll_busy = True
        def work():
            try:
                runner = AndroidRunner(tools, lambda _: None, lambda _: None)
                result = {'sdk': tools['sdk'], 'targets': runner.list_targets(known)}
            except Exception as error:
                result = {'sdk': tools['sdk'], 'error': str(error)}
            if not self.closing: self.events.inventory.emit(result)
        self.inventory_thread = threading.Thread(target=work, daemon=True)
        self.inventory_thread.start()

    def inventory_updated(self, result):
        self.poll_busy = False
        if self.closing or result['sdk'] != self.tools()['sdk']: return
        if result.get('error'):
            if result['error'] != self.last_poll_error:
                self.append_log('Warning: Không cập nhật được thiết bị: ' + result['error'])
            self.last_poll_error = result['error']
            return
        self.last_poll_error = None
        self.devices_scanned(result['targets'])
        if self.pick_running_on_refresh:
            self.pick_running_on_refresh = False
            self.pick_running_emulator()

    def scan_devices(self):
        if self.busy: return
        self.pick_running_on_refresh = self.mode.currentData() == 'emulator'
        self.poll_devices(force=True)

    def pick_running_emulator(self):
        if self.mode.currentData() != 'emulator': return
        selected = self.device.currentData()
        if selected and selected.get('state') == 'device' and selected.get('serial'): return
        running = [i for i in range(self.device.count()) if self.device.itemData(i, BOOTED_ROLE)]
        if running: self.device.setCurrentIndex(running[0])

    def devices_scanned(self, devices):
        for device in devices:
            if device.get('avd') and device.get('serial'):
                self.known_avds[device['serial']] = device['avd']
        if devices != self.devices:
            self.devices = devices; self.filter_devices()
        self.update_target_notice()
        self.sync_logcat()

    def update_target_notice(self):
        selected = self.device.currentData()
        if selected:
            state = {'device': 'sẵn sàng', 'stopped': 'đang tắt', 'booting': 'đang khởi động', 'unauthorized': 'chưa xác nhận RSA', 'offline': 'mất kết nối', 'disconnected': 'mất kết nối'}.get(selected['state'], selected['state'])
            self.device_notice.setText(f'Đang điều khiển: {selected["name"]} · {state}. Chỉ thao tác trên máy này.')
        else:
            self.device_notice.setText('Chọn một thiết bị trong dropdown. Trạng thái tự cập nhật; không tự chuyển sang máy khác.')

    def mode_changed(self):
        if not hasattr(self, 'device'): return
        emulator = self.mode.currentData() == 'emulator'
        self.emulator_controls.setVisible(emulator)
        self.physical_controls.setVisible(not emulator)
        self.filter_devices()
        if not self.loading: self.save()

    def target_changed(self):
        if self.loading: return
        selected = self.device.currentData()
        if selected: self.selected_targets[selected['kind']] = selected['id']
        else: self.selected_targets.pop(self.mode.currentData(), None)
        self.update_target_notice()
        self.sync_logcat()
        self.update_actions() if hasattr(self, 'build_button') else None
        if self.info: self.save()

    def filter_devices(self):
        if not hasattr(self, 'device'): return
        kind = self.mode.currentData()
        previous = self.device.currentData()
        desired = self.selected_targets.get(kind, '')
        if previous and previous.get('kind') == kind: desired = previous['id']
        self.device.blockSignals(True); self.device.clear()
        self.device.addItem('Chọn máy ảo…' if kind == 'emulator' else 'Chọn điện thoại…', None)
        found = False
        for target in self.devices:
            if target['kind'] != kind: continue
            label = f'{target["name"]} · {target["state"]}'
            if target.get('serial'): label += ' · ' + target['serial']
            self.device.addItem(label, target)
            self.device.setItemData(self.device.count()-1, target['kind'] == 'emulator' and target['state'] == 'device' and bool(target.get('serial')), BOOTED_ROLE)
            pinned = previous and previous.get('kind') == kind and previous.get('serial')
            same_serial = (pinned and target.get('serial') == previous['serial']
                           and (not previous.get('avd') or target.get('avd') == previous['avd']))
            same_stopped_avd = pinned and not target.get('serial') and target.get('avd') == previous.get('avd')
            match = (same_serial or same_stopped_avd) if pinned else target['id'] == desired
            if match:
                self.device.setCurrentIndex(self.device.count()-1); found = True
                self.selected_targets[kind] = target['id']
        if desired and not found:
            ghost = dict(previous) if previous and previous.get('id') == desired else {'id': desired, 'name': desired.split(':',1)[-1], 'kind': kind, 'serial': ''}
            ghost['state'] = 'disconnected'
            if desired.startswith('avd:'): ghost['avd'] = desired.split(':', 1)[1]
            self.device.addItem(ghost['name'] + ' · mất kết nối', ghost)
            self.device.setCurrentIndex(self.device.count()-1)
        self.device.blockSignals(False)
        if hasattr(self, 'refresh_hint'): self.refresh_hint.sync()
        if hasattr(self, 'device_notice'): self.update_target_notice()
        self.sync_logcat()
        self.update_actions() if hasattr(self, 'build_button') else None

    def warn_user(self, title, message):
        self.append_log('Warning: ' + message)
        self.set_status(message)
        QMessageBox.warning(self, title, message)

    def stop_polling(self):
        self.closing = True
        self.stop_auto_logcat()
        self.device_timer.stop()
        self.refresh_hint.timer.stop()
        self.refresh_hint.clear()

    def prepare_create_avd(self):
        self.task('Đọc system images và model', lambda runner: runner.avd_catalog(), self.show_create_avd)

    def show_create_avd(self, catalog):
        if not catalog['images'] or not catalog['devices']:
            QMessageBox.information(self, 'Thiếu system image', 'Cài system image và Command-line Tools trong Android Studio → SDK Manager, rồi thử lại.'); return
        dialog = QDialog(self); dialog.setWindowTitle('Tạo Android Virtual Device'); form = QFormLayout(dialog)
        name = QLineEdit('Cocos_Android'); form.addRow('Tên AVD', name)
        image = QComboBox(); image.addItems(catalog['images']); form.addRow('System image đã cài', image)
        device = QComboBox(); device.addItems(catalog['devices']); form.addRow('Model', device)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept); buttons.rejected.connect(dialog.reject); form.addRow(buttons)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            values = name.text().strip(), image.currentText(), device.currentText()
            self.task('Tạo AVD', lambda runner: runner.create_avd(*values), self.avd_created)

    def avd_created(self, name):
        self.mode.setCurrentIndex(0)
        self.device.setCurrentIndex(0)
        self.selected_targets['emulator'] = 'avd:' + name
        self.filter_devices()
        self.poll_devices(force=True)

    def selected_avd(self):
        target = self.device.currentData()
        if not target or target['kind'] != 'emulator' or not target.get('avd'):
            self.warn_user('Chưa chọn AVD', 'Chọn máy ảo trong dropdown thiết bị trước khi thao tác.')
            return None
        return target

    def start_avd(self):
        target = self.selected_avd()
        if target:
            name = target['avd']
            self.task('Mở AVD', lambda runner: runner.start_avd(name), self.avd_started)

    def avd_started(self, message):
        self.set_status(message); self.poll_devices(force=True)

    def stop_avd(self):
        target = self.selected_avd()
        if not target: return
        if not target.get('serial'):
            self.warn_user('Máy ảo chưa chạy', f'{target["name"]} đang tắt hoặc chưa kết nối.'); return
        if QMessageBox.question(self, 'Tắt Android Emulator?', f'Tắt {target["name"]} ({target["serial"]})?') != QMessageBox.StandardButton.Yes: return
        self.task('Tắt máy ảo', lambda runner: runner.adb(runner.require_target(target, require_boot=False)['serial'], ['emu', 'kill']), lambda _: self.poll_devices(force=True))

    def delete_avd(self):
        target = self.selected_avd()
        if not target: return
        name = target['avd']
        if QMessageBox.warning(self, 'Xóa AVD và toàn bộ dữ liệu?', f'Xóa vĩnh viễn AVD {name} và dữ liệu của máy ảo này?', QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Yes, QMessageBox.StandardButton.Cancel) != QMessageBox.StandardButton.Yes: return
        def removed(_):
            self.selected_targets.pop('emulator', None); self.device.setCurrentIndex(0); self.poll_devices(force=True)
        self.task('Xóa AVD', lambda runner: runner.delete_avd(name), removed)

    def pair_wireless(self):
        address = self.address.text().strip()
        code, ok = QInputDialog.getText(self, 'Wireless debugging · Pair', 'Nhập mã 6 số trên điện thoại. Ô địa chỉ phải dùng cổng Pair.', QLineEdit.EchoMode.Password)
        if ok: self.task('Pair Android', lambda runner: runner.wireless(address, code), self.wireless_connected)

    def connect_wireless(self):
        address = self.address.text().strip()
        self.task('Connect Android', lambda runner: runner.wireless(address), self.wireless_connected)

    def wireless_connected(self, result):
        self.set_status(result['message'] if isinstance(result, dict) else result)
        if isinstance(result, dict) and result.get('serial'):
            self.device.setCurrentIndex(0)
            self.selected_targets['device'] = 'serial:' + result['serial']
            self.mode.setCurrentIndex(1)
            self.filter_devices()
        self.poll_devices(force=True)

    def pair_qr_code(self):
        if self.busy: return
        from android_wifi import new_pairing_session, qr_matrix, pair_qr
        try:
            session = new_pairing_session()
            matrix = qr_matrix(session.payload)
        except BuildError as error:
            self.warn_user('Chưa thể tạo QR', str(error)); return
        dialog = QDialog(self); dialog.setWindowTitle('Kết nối Android bằng QR · Wireless debugging')
        layout = QVBoxLayout(dialog)
        instructions = QLabel('Android 11+: bật Developer options → Wireless debugging → Pair device with QR code.\nĐiện thoại và Mac dùng cùng mạng Wi-Fi. Quét QR bên dưới trong 2 phút.')
        instructions.setWordWrap(True); layout.addWidget(instructions)
        scale = 6; size = len(matrix) * scale
        image = QImage(size, size, QImage.Format.Format_RGB32); image.fill(QColor('white'))
        painter = QPainter(image)
        for y, row in enumerate(matrix):
            for x, black in enumerate(row):
                if black: painter.fillRect(x * scale, y * scale, scale, scale, QColor('black'))
        painter.end()
        code = QLabel(); code.setPixmap(QPixmap.fromImage(image)); code.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(code)
        layout.addWidget(QLabel('Đang chờ điện thoại quét QR… Đóng cửa sổ để hủy và làm hết hạn phiên này.'))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        buttons.rejected.connect(dialog.reject); layout.addWidget(buttons)
        dialog.rejected.connect(self.cancel)
        self.qr_dialog = dialog
        self.task('Ghép đôi Wi-Fi bằng QR', lambda runner: pair_qr(runner, session), self.wireless_connected)
        if self.busy: dialog.exec()
        self.qr_dialog = None

    def current_options(self):
        return self.build_config.options()

    def start_build(self, run):
        if self.busy: return
        if not self.info or not self.config.currentData():
            AndroidRunner(self.tools(), self.events.log.emit, self.events.stage.emit).log_toolchain()
            self.warn_user('Chưa thể build Android', 'Chọn project và task Cocos Android trước. Nếu chưa có task, mở Cocos để tạo và lưu task Android.'); return
        root, options, device = self.info['root'], self.current_options(), self.device.currentData()
        if run and not device:
            AndroidRunner(self.tools(), self.events.log.emit, self.events.stage.emit).log_toolchain(options)
            self.warn_user('Chưa chọn thiết bị', 'Chọn thiết bị trong dropdown trước khi Build & Run. Có thể mở AVD hoặc kết nối điện thoại USB / Wi-Fi.'); return
        error = validate_android_options(options)
        if error:
            AndroidRunner(self.tools(), self.events.log.emit, self.events.stage.emit).log_toolchain(options)
            self.warn_user('Cấu hình Android', error); return
        native_only = self.native_only.isChecked()
        if native_only:
            exported_options = make_android_config(options, self.tools(), options['packages']['android']['packageName'])
            record = export_folder(Path(root), exported_options) / '.android-builder-apk.json'
            try: unchanged = json.loads(record.read_text()).get('config') == strip_secrets(exported_options)
            except (OSError, ValueError): unchanged = False
            if not unchanged:
                QMessageBox.information(self, 'Cần export Cocos', 'Cấu hình chưa có APK khớp. Tool sẽ xuất lại Cocos trước khi build.'); native_only = False
        def work(runner):
            runner.log_toolchain(options)
            exported = export_folder(Path(root), make_android_config(options, runner.tools, options['packages']['android']['packageName']))
            if (exported / 'proj/gradlew').is_file(): runner.ensure_gradle_java(exported / 'proj')
            selected = runner.require_target(device) if run else None
            apk = runner.build_apk(root, options, native_only)
            if run:
                selected = runner.require_target(selected)
                runner.install_run(apk, selected['serial'], options['packages']['android']['packageName'])
            return apk
        self.task('Build & Run Android' if run else 'Build APK', work, self.apk_built)

    def apk_built(self, apk):
        self.last_apk = apk; self.manual_apk = False; self.apk.setText(apk); self.save()
        self.append_log('APK: ' + apk)

    def choose_apk(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Chọn APK để cài thử', self.last_apk, 'Android APK (*.apk)')
        if path: self.last_apk = path; self.manual_apk = True; self.apk.setText(path); self.save()

    def run_apk(self, clean):
        if not self.info: return
        device = self.device.currentData()
        if not device or device['state'] != 'device': return
        root, options = self.info['root'], self.current_options()
        package = options.get('packages', {}).get('android', {}).get('packageName', '')
        if not package:
            QMessageBox.information(self, 'Package ID', 'Chọn task Android có Package ID trước khi chạy APK.'); return
        if clean and QMessageBox.warning(self, 'Clean & Run · Xóa dữ liệu?', f'Kiểm tra APK rồi gỡ {package} trên {device["name"]} ({device["serial"]}), xóa dữ liệu và cài lại?', QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Yes, QMessageBox.StandardButton.Cancel) != QMessageBox.StandardButton.Yes: return
        selected = self.last_apk if getattr(self, 'manual_apk', False) else ''
        def work(runner):
            runner.log_toolchain(options)
            apk = selected or runner.existing_apk(root, options)
            target = runner.require_target(device)
            return runner.install_run(apk, target['serial'], package, clean)
        self.task('Clean & Run Android' if clean else 'Run Android APK', work, lambda value: self.apk.setText(value))

    def stop_auto_logcat(self):
        runner, self.log_runner = self.log_runner, None
        self.log_target = None
        if runner: runner.cancel()

    def sync_logcat(self):
        if self.loading: return
        selected = self.device.currentData()
        serial = selected.get('serial') if selected and selected.get('state') in ('device', 'booting') else ''
        target = (self.tools().get('sdk', ''), serial) if serial and not self.closing else None
        if target == self.log_target and self.log_runner is not None: return
        self.stop_auto_logcat()
        if not target: return
        runner = AndroidRunner(self.tools(), lambda text: self.events.log.emit(text) if self.log_runner is runner and not self.closing else None, lambda _: None)
        self.log_runner, self.log_target = runner, target
        self.append_log('Logcat: tự động theo thiết bị ' + serial + ' · ghi vào bảng log chung.')
        def monitor():
            error = ''
            try: runner.logcat(serial)
            except Exception as failure:
                if not runner.cancelled.is_set(): error = str(failure)
            if not self.closing: self.events.logcat_done.emit({'runner': runner, 'error': error})
        self.log_thread = threading.Thread(target=monitor, daemon=True)
        self.log_thread.start()

    def logcat_finished(self, result):
        if result['runner'] is not self.log_runner: return
        self.log_runner = None
        self.log_target = None
        if result['error'] and result['error'] != self.last_logcat_error:
            self.append_log('Warning: Logcat tạm ngắt: ' + result['error'] + ' · sẽ tự thử lại khi thiết bị sẵn sàng.')
        self.last_logcat_error = result['error'] or None

    def append_log(self, text):
        self.pending.extend(re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]', '', text).splitlines())

    def matches(self, line):
        level = self.log_level.currentData()
        return self.log_filter.text().lower() in line.lower() and (level == 'all' or LogHighlighter.level(line) == level)

    def flush_log(self):
        if not self.pending: return
        lines, self.pending = self.pending, []
        dropping = len(self.history) + len(lines) > self.history.maxlen
        self.history.extend(lines)
        if dropping and (self.log_filter.text() or self.log_level.currentData() != 'all'):
            self.refresh_log(); return
        visible = [line for line in lines if self.matches(line)]
        if visible: self.log.appendPlainText('\n'.join(visible)); self.log.moveCursor(QTextCursor.MoveOperation.End)

    def refresh_log(self):
        self.log.setPlainText('\n'.join(line for line in self.history if self.matches(line)))
        self.log.moveCursor(QTextCursor.MoveOperation.End)

    def clear_log(self):
        self.pending.clear(); self.history.clear(); self.log.clear()
