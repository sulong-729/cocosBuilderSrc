"""Shared plain-text log colors for iOS and Android."""
import re
from PySide6.QtGui import QSyntaxHighlighter, QTextCharFormat, QColor


class LogHighlighter(QSyntaxHighlighter):
    """Color whole log lines without changing their text or filtering."""

    error_pattern = re.compile(r"\b(?:errors?|exceptions?|failed|failure|fatal|sigabrt|sigsegv|exc_bad_access|crash(?:ed)?)\b", re.IGNORECASE)
    warning_pattern = re.compile(r"\b(?:warn(?:ing)?s?|warring)\b", re.IGNORECASE)

    def __init__(self, document):
        super().__init__(document)
        self.formats = {}
        for level, color in (("toolchain", "#8cdda4"), ("normal", "#ffffff"), ("error", "#ff6b6b"), ("warning", "#ffd166")):
            style = QTextCharFormat()
            style.setForeground(QColor(color))
            self.formats[level] = style

    @classmethod
    def level(cls, text):
        if text.startswith("[Android Tools]"):
            return "toolchain"
        logcat = re.match(r'^\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\.\d+\s+\d+\s+\d+\s+([VDIWEF])\s', text)
        if logcat:
            return {'E': 'error', 'F': 'error', 'W': 'warning'}.get(logcat[1], 'normal')
        if cls.error_pattern.search(text) or re.search(r'\b[A-Za-z_$][\w$]*(?:Error|Exception)\b', text):
            return "error"
        if cls.warning_pattern.search(text):
            return "warning"
        return "normal"

    def highlightBlock(self, text):
        self.setFormat(0, len(text), self.formats[self.level(text)])
