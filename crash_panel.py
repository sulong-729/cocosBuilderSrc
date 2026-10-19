"""Passive crash monitor: no debugger attachment and no app lifecycle commands."""
import plistlib
import re
import threading
from pathlib import Path
from PySide6.QtCore import QTimer, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox, QPlainTextEdit
from diagnostics import read_report, matches, symbolicate, format_report, source_excerpt


class CrashPanel(QWidget):
    completed = Signal(object, str, bool)

    def __init__(self, context, parent=None):
        super().__init__(parent)
        self.context = context
        self.busy = False
        self.scope = None
        self.seen = set()
        self.reports = []
        self.completed.connect(self.loaded)
        layout = QVBoxLayout(self)
        self.notice = QLabel('Tự theo dõi crash report Simulator mỗi 3 giây. iPhone USB: nhập .ips đã xuất từ thiết bị.\nKhông dừng, khởi động lại hay gắn debugger vào game.')
        self.notice.setWordWrap(True)
        layout.addWidget(self.notice)
        row = QHBoxLayout()
        self.history = QComboBox()
        self.history.currentIndexChanged.connect(self.show_report)
        row.addWidget(self.history,1)
        refresh = QPushButton('Quét crash')
        refresh.clicked.connect(lambda: self.poll(True))
        row.addWidget(refresh)
        from PySide6.QtWidgets import QFileDialog
        load = QPushButton('Mở .ips')
        def import_report():
            path,_ = QFileDialog.getOpenFileName(self,'Mở crash report','','Crash report (*.ips)')
            if path: self.start([Path(path)],False)
        load.clicked.connect(import_report)
        row.addWidget(load)
        layout.addLayout(row)
        self.frames = QComboBox()
        self.frames.currentIndexChanged.connect(self.show_source)
        layout.addWidget(self.frames)
        self.detail = QPlainTextEdit()
        self.detail.setReadOnly(True)
        self.detail.setFont(QFont('Menlo',11))
        layout.addWidget(self.detail,2)
        self.source = QPlainTextEdit()
        self.source.setReadOnly(True)
        self.source.setFont(QFont('Menlo',11))
        self.source.setPlaceholderText('Chọn frame để xem đoạn source nếu có symbol file/dòng.')
        layout.addWidget(self.source,1)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.poll)
        self.timer.start(3000)

    def poll(self, force=False):
        if self.busy: return
        project,bundle,device = self.context()
        if not project or not bundle or not device: return
        scope=(project,bundle,device)
        if scope != self.scope:
            self.scope=scope
            self.seen.clear()
            self.reports.clear()
            self.history.clear()
            self.frames.clear()
            self.detail.clear()
            self.source.clear()
        folder=Path.home()/'Library/Logs/DiagnosticReports'
        paths=sorted(folder.glob('*.ips'),key=lambda p:p.stat().st_mtime,reverse=True)[:150]
        self.start([p for p in paths if str(p) not in self.seen],True)

    def start(self,paths,scoped):
        if self.busy or not paths: return
        project,bundle,device=self.context()
        if not project: return
        scope=(project,bundle,device)
        self.busy=True
        def work():
            reports=[]; error=''
            try:
                names=set()
                for p in (Path(project)/'build').glob('**/*.app/Info.plist'):
                    try:
                        info=plistlib.loads(p.read_bytes())
                        if info.get('CFBundleIdentifier')==bundle: names.add(info.get('CFBundleExecutable',''))
                    except (OSError,ValueError): pass
                for p in reversed(paths):
                    try:
                        report=read_report(p)
                        if not scoped or any(matches(report,name,device) for name in names):
                            reports.append(symbolicate(report,project))
                    except (ValueError,OSError,KeyError,TypeError): continue
            except Exception as exc: error=str(exc)
            self.completed.emit((scope,reports,[str(p) for p in paths]),error,scoped)
        threading.Thread(target=work,daemon=True).start()

    def loaded(self,result,error,scoped):
        self.busy=False
        scope,reports,paths=result
        if scoped and scope != self.scope: return
        self.seen.update(paths)
        if error: self.notice.setText('Không đọc được crash: '+error)
        for report in reports:
            self.reports.append(report)
            self.history.addItem(f"{report['header'].get('timestamp','')} · {report['name']}")
        if reports:
            self.history.setCurrentIndex(len(self.reports)-1)
            self.notice.setText('Đã bắt crash native. Chọn frame để xem code; chỉ hiện dòng khi symbol khớp UUID.')
            tabs=self.parentWidget()
            # Notify without stealing focus from the user.
            self.setToolTip('Có crash native mới')

    def show_report(self,index):
        self.frames.clear(); self.source.clear()
        if not 0 <= index < len(self.reports): return
        report=self.reports[index]
        self.detail.setPlainText(format_report(report))
        for i,f in enumerate(report['frames']):
            self.frames.addItem(f"#{i} {f.get('resolved') or f.get('symbol') or hex(f['address'])}",f.get('resolved',''))

    def show_source(self,index):
        symbol=self.frames.currentData() or ''
        match=re.search(r'\((/.*?):(\d+)(?::\d+)?\)',symbol)
        if match:
            self.source.setPlainText(f'{match[1]}:{match[2]}\n\n'+source_excerpt(match[1],int(match[2])))
        else:
            self.source.setPlainText('Frame này chưa có đường dẫn source/dòng trong symbol. Xem tên hàm và các frame bên dưới.')
