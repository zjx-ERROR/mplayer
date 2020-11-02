from subprocess import PIPE
from PyQt5 import QtCore
from PyQt5.QtWidgets import QWidget as _Container
from PyQt5.QtWidgets import QApplication, QSystemTrayIcon, QMenu, QAction
from core import Player
import misc
from PyQt5.QtCore import Qt, pyqtSignal,QMutex
from PyQt5.QtGui import QKeyEvent, QIcon
import config
from PyQt5.QtNetwork import QUdpSocket, QHostAddress,QAbstractSocket
import argparse
import sys
import glob
import ctypes

__all__ = ['QtPlayer', 'QPlayerView']


class QtPlayer(Player):

    def __init__(self, args=(), stdout=PIPE, stderr=None, autospawn=True):
        super(QtPlayer, self).__init__(args, autospawn=False)
        self._stdout = _StdoutWrapper(handle=stdout)
        self._stderr = _StderrWrapper(handle=stderr)
        if autospawn:
            self.spawn()


class QPlayerView(_Container):
    eof = pyqtSignal(int)
    play_status = 0
    WM_APPCOMMAND = 0x319
    APPCOMMAND_VOLUME_UP = 0x0a
    APPCOMMAND_VOLUME_DOWN = 0x09
    APPCOMMAND_VOLUME_MUTE = 0x08

    def __init__(self, parent=None, args=(), stderr=None, udp=False):
        super(QPlayerView, self).__init__(parent)
        self._player = QtPlayer(('-msglevel', 'global=6', '-fixed-vo', '-fs',
                                 '-wid', int(self.winId())) + args, stderr=stderr)
        self._player.stdout.connect(self._handle_data)
        self.destroyed.connect(self._on_destroy)

        self.tray_wid()
        self.qmutex = QMutex()
        if udp:
            self.udp_slave(int(config.port1), int(config.port2))

    def setVol(self, appcommand):
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        ctypes.windll.user32.PostMessageA(hwnd, self.WM_APPCOMMAND, 0, appcommand * 0x10000)

    @property
    def player(self):
        return self._player

    def _on_destroy(self):
        self._player.quit()

    def _handle_data(self, data):
        if data.startswith('EOF code:'):
            code = data.partition(':')[2].strip()
            self.eof.emit(int(code))

    def keyPressEvent(self, QKeyEvent):
        if QKeyEvent.key() == Qt.Key_Space:
            self._player.pause()
            self.set_play_status()
        elif QKeyEvent.key() == Qt.Key_Escape:
            if self.play_status:
                self._player.pause()
                self.set_play_status()
            self.hide()
            self.tray.show()

        elif QKeyEvent.modifiers() == Qt.ControlModifier and QKeyEvent.key() == Qt.Key_C:
            self._player.loadlist(config.list_dir)

    def udp_slave(self, port1, port2):
        self.socket1 = QUdpSocket()
        self.socket2 = QUdpSocket()

        self.socket1.bind(QHostAddress(config.host), port1)
        self.socket2.bind(QHostAddress(config.host), port2)
        self.socket1.readyRead.connect(self.on_udp_receive1)
        self.socket2.readyRead.connect(self.on_udp_receive2)

    def on_udp_receive1(self):
        data, host, port = self.socket1.readDatagram(512)
        self.handle_datagram(data)

    def on_udp_receive2(self):
        data, host, port = self.socket2.readDatagram(512)
        self.handle_datagram(data)

    def handle_datagram(self, data):
        ddata = data.decode("utf-8")
        if ddata == "Space":
            if self.tray.isVisible():
                self.showFullScreen()
                self.tray.hide()
            self._player.pause()
            self.set_play_status()

        elif ddata == "raise":
            self.setVol(self.APPCOMMAND_VOLUME_UP)
        elif ddata == "reduce":
            self.setVol(self.APPCOMMAND_VOLUME_DOWN)
        elif ddata == "FT1":
            self._player.loadlist(config.list_dir)

    def tray_wid(self):
        self.tray = QSystemTrayIcon()
        self.icon = QIcon('gy.ico')
        self.tray.setIcon(self.icon)
        self.tray.activated.connect(self.tray_on_activate)
        self.tray_menu = QMenu(QApplication.desktop())
        self.restore_action = QAction(u'退出', self, triggered=self.exit)
        self.tray_menu.addAction(self.restore_action)
        self.tray.setContextMenu(self.tray_menu)

    def tray_on_activate(self, reason):
        if reason == self.tray.Trigger:
            self.show()
            self.tray.hide()

    def set_play_status(self):
        self.qmutex.lock()
        self.play_status = pow((self.play_status - 1), 2)
        self.qmutex.unlock()

    def exit(self):
        sys.exit(15)


class _StderrWrapper(misc._StderrWrapper):

    def __init__(self, **kwargs):
        super(_StderrWrapper, self).__init__(**kwargs)
        self._notifier = None

    def _attach(self, source):
        super(_StderrWrapper, self)._attach(source)
        self._notifier = QtCore.QSocketNotifier(self._source.fileno(),
                                                QtCore.QSocketNotifier.Read)
        self._notifier.activated.connect(self._process_output)

    def _detach(self):
        self._notifier.setEnabled(False)
        super(_StderrWrapper, self)._detach()


class _StdoutWrapper(_StderrWrapper, misc._StdoutWrapper):
    pass


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('-u', '--udp', default=False, required=True, type=bool)
    args = parser.parse_args()

    with open(config.list_dir, "w", encoding="utf-8") as f:
        f.writelines([i + "\n" for i in glob.glob(config.media_list_dir)])

    app = QApplication(sys.argv)
    v = QPlayerView(udp=args.udp)

    v.eof.connect(app.closeAllWindows)
    v.setWindowTitle('MPlayer')
    v.grabKeyboard()
    v.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
    v.showFullScreen()

    v.player.loadlist(config.list_dir)
    v.player.pause()
    sys.exit(app.exec_())
