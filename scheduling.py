"""One live timer, reconfigured without starting concurrent device queries."""
from PySide6.QtCore import QTimer
from settings import REFRESH_INTERVALS


class RefreshTimer(QTimer):
    def __init__(self,callback,seconds=15,parent=None):
        super().__init__(parent);self.timeout.connect(callback);self.set_seconds(seconds)

    def set_seconds(self,seconds):
        if type(seconds) is not int or seconds not in REFRESH_INTERVALS:raise ValueError('Invalid refresh interval')
        milliseconds=seconds*1000
        if self.interval()!=milliseconds:self.setInterval(milliseconds)
