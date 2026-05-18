import json
import queue
import socket
import sys
import threading
import time

from PySide6.QtCore import Qt, QPoint, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication,
    QWidget,
    QLabel,
    QLineEdit,
    QPushButton,
    QHBoxLayout,
    QVBoxLayout,
    QButtonGroup,
    QRadioButton,
)


HOST = "127.0.0.1"


class Overlay(QWidget):
    def __init__(self, port):
        super().__init__()

        self.port = port
        self.sock = None
        self.incoming = queue.Queue()
        self.drag_pos = QPoint()
        self.can_submit = False

        self.setWindowTitle("Reachy Chat")
        self.setWindowFlags(Qt.WindowStaysOnTopHint)
        self.resize(720, 210)
        self.move(300, 650)

        self.build_ui()
        self.connect_socket()

        self.poll_timer = QTimer()
        self.poll_timer.timeout.connect(self.process_incoming)
        self.poll_timer.start(50)

    def build_ui(self):
        self.title = QLabel("Reachy Check-in")
        self.title.setObjectName("title")

        self.condition_label = QLabel("EMPATHETIC")
        self.condition_label.setObjectName("conditionLabel")

        top = QHBoxLayout()
        top.addWidget(self.title)
        top.addWidget(self.condition_label)
        top.addStretch()

        self.subtitle = QLabel("Connecting...")
        self.subtitle.setWordWrap(True)
        self.subtitle.setObjectName("subtitle")

        self.input = QLineEdit()
        self.input.setPlaceholderText("Type answer...")
        self.input.returnPressed.connect(self.submit)
        self.input.textChanged.connect(self.update_submit_button)

        self.submit_btn = QPushButton("Submit")
        self.submit_btn.clicked.connect(self.submit)

        self.start_btn = QPushButton("Start")
        self.start_btn.clicked.connect(self.start_interview)

        input_row = QHBoxLayout()
        input_row.addWidget(self.input, stretch=1)
        input_row.addWidget(self.submit_btn)
        input_row.addWidget(self.start_btn)

        self.emp_radio = QRadioButton("Empathetic")
        self.neu_radio = QRadioButton("Neutral")
        self.emp_radio.setChecked(True)

        self.group = QButtonGroup()
        self.group.addButton(self.emp_radio)
        self.group.addButton(self.neu_radio)

        self.emp_radio.clicked.connect(lambda: self.set_condition("empathetic"))
        self.neu_radio.clicked.connect(lambda: self.set_condition("neutral"))

        bottom = QHBoxLayout()
        bottom.addWidget(self.emp_radio)
        bottom.addWidget(self.neu_radio)
        bottom.addStretch()

        layout = QVBoxLayout()
        layout.addLayout(top)
        layout.addWidget(self.subtitle)
        layout.addLayout(input_row)
        layout.addLayout(bottom)

        self.setLayout(layout)

        self.setStyleSheet("""
            QWidget {
                background-color: #080c12;
                color: white;
                font-family: Helvetica;
            }

            QLabel#title {
                font-size: 22px;
                font-weight: 800;
            }

            QLabel#conditionLabel {
                color: #93c5fd;
                background-color: #1e3a8a;
                border-radius: 10px;
                padding: 5px 10px;
                font-size: 12px;
                font-weight: 700;
            }

            QLabel#subtitle {
                color: white;
                background-color: #0f172a;
                border-radius: 14px;
                font-size: 17px;
                padding: 14px;
                min-height: 70px;
            }

            QLineEdit {
                color: white;
                background-color: #1e293b;
                border: 1px solid #475569;
                border-radius: 12px;
                padding: 11px;
                font-size: 16px;
            }

            QLineEdit:disabled {
                color: #64748b;
                background-color: #111827;
            }

            QPushButton {
                color: white;
                background-color: #2563eb;
                border: none;
                border-radius: 12px;
                padding: 11px 16px;
                font-size: 15px;
                font-weight: 800;
            }

            QPushButton:disabled {
                background-color: #334155;
                color: #94a3b8;
            }

            QPushButton:hover {
                background-color: #1d4ed8;
            }

            QRadioButton {
                color: #d1d5db;
                font-size: 13px;
                padding: 2px;
            }
        """)

        self.set_input_enabled(False)

    def set_input_enabled(self, enabled):
        self.can_submit = enabled
        self.input.setEnabled(enabled)
        self.submit_btn.setEnabled(enabled and bool(self.input.text().strip()))

        self.subtitle.setStyleSheet("""
            color: white;
            background-color: #0f172a;
            border-radius: 14px;
            font-size: 17px;
            padding: 14px;
            min-height: 70px;
        """)

        if enabled:
            self.input.setPlaceholderText("Your turn — type answer...")
            self.input.setStyleSheet("""
                color: white;
                background-color: #10251a;
                border: 2px solid #22c55e;
                border-radius: 12px;
                padding: 11px;
                font-size: 16px;
            """)
            self.raise_()
            self.activateWindow()
            self.input.setFocus()
        else:
            self.input.setPlaceholderText("Wait for Reachy to finish...")
            self.input.setStyleSheet("""
                color: #64748b;
                background-color: #111827;
                border: 1px solid #334155;
                border-radius: 12px;
                padding: 11px;
                font-size: 16px;
            """)

    def update_submit_button(self):
        self.submit_btn.setEnabled(self.can_submit and bool(self.input.text().strip()))

    def start_interview(self):
        self.start_btn.setEnabled(False)
        self.send({"type": "start"})
        QTimer.singleShot(1200, lambda: self.start_btn.setEnabled(True))

    def closeEvent(self, event):
        self.send({"type": "shutdown"})
        event.accept()

    def connect_socket(self):
        def worker():
            while True:
                try:
                    self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    self.sock.connect((HOST, self.port))
                    break
                except Exception:
                    time.sleep(0.15)

            buffer = ""

            while True:
                try:
                    data = self.sock.recv(4096).decode("utf-8")

                    if not data:
                        break

                    buffer += data

                    while "\n" in buffer:
                        line, buffer = buffer.split("\n", 1)

                        if line.strip():
                            self.incoming.put(json.loads(line))

                except Exception:
                    break

        threading.Thread(target=worker, daemon=True).start()

    def send(self, payload):
        if not self.sock:
            return

        try:
            self.sock.sendall((json.dumps(payload) + "\n").encode("utf-8"))
        except Exception:
            pass

    def submit(self):
        if not self.can_submit:
            return

        text = self.input.text().strip()

        if not text:
            return

        self.input.clear()
        self.set_input_enabled(False)

        self.send({
            "type": "submit",
            "text": text,
        })

    def set_condition(self, condition):
        self.send({
            "type": "condition",
            "condition": condition,
        })

    def process_incoming(self):
        while not self.incoming.empty():
            msg = self.incoming.get()
            kind = msg.get("type")

            if kind == "shutdown":
                self.close()
                return

            condition = msg.get("condition", "empathetic")
            awaiting = msg.get("awaiting", False)

            if condition == "empathetic":
                self.emp_radio.setChecked(True)
            else:
                self.neu_radio.setChecked(True)

            self.condition_label.setText(condition.upper())

            if kind == "speech_start":
                self.subtitle.setText("")
                self.set_input_enabled(False)

            elif kind == "subtitle":
                self.subtitle.setText(msg.get("text", ""))
                self.set_input_enabled(False)

            elif kind == "speech_done":
                self.set_input_enabled(awaiting)

            elif kind == "status":
                self.subtitle.setText(msg.get("text", ""))
                self.set_input_enabled(awaiting)


def main():
    app = QApplication(sys.argv)
    app.setFont(QFont("Helvetica"))

    port = int(sys.argv[1])

    overlay = Overlay(port)
    overlay.show()
    overlay.raise_()
    overlay.activateWindow()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()