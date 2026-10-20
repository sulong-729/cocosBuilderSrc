"""Compact, animated status painted inside each platform tab."""
from PySide6.QtCore import Qt, QTimer, QRectF, QSize
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap, QIcon
from PySide6.QtWidgets import QWidget


def platform_icon(android=False):
    pixmap = QPixmap(24, 24)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(QColor('#8cdda4' if android else '#b8cee8'), 1.8))
    if android:
        painter.drawArc(QRectF(5, 6, 14, 12), 0, 180 * 16)
        painter.drawLine(7, 6, 5, 3); painter.drawLine(17, 6, 19, 3)
        painter.drawRoundedRect(QRectF(5, 12, 14, 8), 2, 2)
        painter.drawPoint(9, 9); painter.drawPoint(15, 9)
        painter.drawLine(8, 20, 8, 23); painter.drawLine(16, 20, 16, 23)
    else:
        painter.drawRoundedRect(QRectF(6, 2, 12, 20), 3, 3)
        painter.drawLine(10, 5, 14, 5); painter.drawPoint(12, 19)
    painter.end()
    return QIcon(pixmap)


class PlatformStatus(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(78, 26)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.busy = False
        self.count = None
        self.angle = 0
        self.timer = QTimer(self)
        self.timer.setInterval(60)
        self.timer.timeout.connect(self.advance)
        self.set_status(False, None)

    def sizeHint(self):
        return QSize(78, 26)

    def set_status(self, busy, count, detail=''):
        self.busy, self.count = bool(busy), count
        self.timer.start() if self.busy else self.timer.stop()
        self.setToolTip(('Đang build / chạy tác vụ' if self.busy else 'Sẵn sàng') + '\n' + (f'{count} thiết bị đang chạy / kết nối' if count is not None else 'Chưa đọc được số thiết bị') + ('\n' + detail if detail else ''))
        self.update()

    def advance(self):
        self.angle = (self.angle + 24) % 360
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = QColor('#8cdda4')
        if self.busy:
            painter.setPen(QPen(color, 2.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawArc(QRectF(2, 5, 16, 16), -self.angle * 16, 260 * 16)
        painter.setPen(QPen(QColor('#b8cee8'), 1.5))
        painter.drawRoundedRect(QRectF(29, 4, 11, 18), 2, 2)
        painter.drawPoint(34, 19)
        painter.setPen(color if self.count else QColor('#98a8ba'))
        painter.drawText(QRectF(46, 0, 30, 26), Qt.AlignmentFlag.AlignVCenter, str(self.count) if self.count is not None else '…')
