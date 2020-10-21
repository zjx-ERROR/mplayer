from subprocess import PIPE

from PyQt5 import QtCore
from PyQt5.QtWidgets import QWidget as _Container
from PyQt5.QtWidgets import QApplication
from core import Player
import misc
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QKeyEvent
import config
from PyQt5.QtNetwork import QUdpSocket, QHostAddress
import argparse
import sys
import glob

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

    def __init__(self, parent=None, args=(), stderr=None,udp=False):
        super(QPlayerView, self).__init__(parent)
        self._player = QtPlayer(('-msglevel', 'global=6', '-fixed-vo', '-fs',
                                 '-wid', int(self.winId())) + args, stderr=stderr)
        self._player.stdout.connect(self._handle_data)
        self.destroyed.connect(self._on_destroy)
        self.volume = float(config.volume)
        if udp:
            self.udp_slave(int(config.port1), int(config.port2))
        # self.udp_slave(int(config.port1), int(config.port2))
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
        elif QKeyEvent.key() == Qt.Key_Escape:
            self.close()
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
        data, host, port = self.socket1.readDatagram(1024)
        self.handle_datagram(data)

    def on_udp_receive2(self):
        data, host, port = self.socket2.readDatagram(1024)
        self.handle_datagram(data)

    def handle_datagram(self, data):
        ddata = data.decode("utf-8")
        if ddata == "Space":
            self._player.pause()
        elif ddata == "raise":
            value = self.volume + 5
            if value <= 100:
                self.volume = value
                self._player.volume = value
            else:
                self.volume = 100
                self._player.volume = 100
        elif ddata == "reduce":
            value = self.volume - 5
            if value >= 0:
                self.volume = value
                self._player.volume = value
            else:
                self.volume = 0
                self._player.volume = 0
        elif ddata == "FT1":
            self._player.loadlist(config.list_dir)


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
    v.setWindowFlags(Qt.FramelessWindowHint)
    v.showFullScreen()

    v.player.loadlist(config.list_dir)
    v.player.pause()
    sys.exit(app.exec_())

