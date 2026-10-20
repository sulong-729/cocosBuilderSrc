"""Shared running-device indicators for iOS and Android dropdowns."""
from PySide6.QtCore import Qt, QSize, QObject, QTimer
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (QApplication, QComboBox, QSizePolicy, QStyledItemDelegate, QStyleOptionViewItem, QStyleOptionComboBox, QStyle)

BOOTED_ROLE = int(Qt.ItemDataRole.UserRole) + 1


def paint_running_dot(painter, rect, metrics, text):
    x = rect.left() + metrics.horizontalAdvance(text) + 9
    if x + 5 <= rect.right():
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#42d883"))
        painter.drawEllipse(x, rect.center().y() - 4, 8, 8)
        painter.restore()


class DeviceDelegate(QStyledItemDelegate):
    def paint(self, painter, option, index):
        super().paint(painter, option, index)
        if index.data(BOOTED_ROLE):
            opt = QStyleOptionViewItem(option)
            self.initStyleOption(opt, index)
            rect = opt.widget.style().subElementRect(QStyle.SubElement.SE_ItemViewItemText, opt, opt.widget)
            paint_running_dot(painter, rect, opt.fontMetrics, opt.text)

    def sizeHint(self, option, index):
        size = super().sizeHint(option, index)
        if index.data(BOOTED_ROLE):
            size.setWidth(size.width() + 24)
        return size


class ReadableComboBox(QComboBox):
    def __init__(self):
        super().__init__()
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.setMinimumContentsLength(8)
        self.view().setTextElideMode(Qt.TextElideMode.ElideNone)
        self.view().setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.currentTextChanged.connect(self.setToolTip)
        self.currentTextChanged.connect(lambda: self.updateGeometry())

    def sizeHint(self):
        width = self.fontMetrics().horizontalAdvance(self.currentText()) + (100 if self.currentData(BOOTED_ROLE) else 76)
        return QSize(min(680, max(180, width)), super().sizeHint().height())

    def minimumSizeHint(self):
        return QSize(min(300, self.sizeHint().width()), self.sizeHint().height())

    def paintEvent(self, event):
        super().paintEvent(event)
        if self.currentData(BOOTED_ROLE):
            option = QStyleOptionComboBox()
            self.initStyleOption(option)
            rect = self.style().subControlRect(QStyle.ComplexControl.CC_ComboBox, option,
                                              QStyle.SubControl.SC_ComboBoxEditField, self)
            painter = QPainter(self)
            paint_running_dot(painter, rect, self.fontMetrics(), self.currentText())

    def showPopup(self):
        metrics = self.fontMetrics()
        longest = max((metrics.horizontalAdvance(self.itemText(i)) for i in range(self.count())), default=0)
        screen = self.screen() or QApplication.primaryScreen()
        width = min(max(self.width(), longest + 96), screen.availableGeometry().width() - 50)
        self.view().setMinimumWidth(width)
        super().showPopup()



class RefreshHint(QObject):
    """Briefly outline Refresh every four seconds while a target is missing."""
    def __init__(self, button, needs_selection):
        super().__init__(button)
        self.button = button
        self.needs_selection = needs_selection
        self.original_style = button.styleSheet()
        self.timer = QTimer(self)
        self.timer.setInterval(4000)
        self.timer.timeout.connect(self.pulse)
        self.fade_timer = QTimer(self)
        self.fade_timer.setSingleShot(True)
        self.fade_timer.setInterval(650)
        self.fade_timer.timeout.connect(self.clear)
        self.timer.start()

    def pulse(self):
        if not self.needs_selection() or not self.button.isVisible() or not self.button.isEnabled():
            self.clear()
            return
        self.button.setStyleSheet(self.original_style + '\nborder: 2px solid #8cdda4; background-color: #294b42;')
        self.fade_timer.start()

    def clear(self, *args):
        self.fade_timer.stop()
        self.button.setStyleSheet(self.original_style)

    def sync(self, *args):
        if not self.needs_selection(): self.clear()
