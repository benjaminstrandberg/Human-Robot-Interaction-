import json
import queue
import random
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import mujoco
import mujoco.viewer
import numpy as np
import reachy_mini

from script_data import (
    QUESTIONS,
    NEGATIVE_KEYWORDS,
    POSITIVE_KEYWORDS,
    BACKCHANNELS,
    INTRO,
    OUTRO,
)
from speech import speak_async


HOST = "127.0.0.1"
PORT = 5555

REACHY_DIR = Path(reachy_mini.__file__).parent
MODEL_PATH = REACHY_DIR / "descriptions/reachy_mini/mjcf/scene.xml"


def classify_answer(text):
    text = text.lower()

    if any(word in text for word in NEGATIVE_KEYWORDS):
        return "negative"

    if any(word in text for word in POSITIVE_KEYWORDS):
        return "positive"

    return "unclear"


class OverlayServer:
    def __init__(self):
        self.messages = queue.Queue()
        self.client = None
        self.lock = threading.Lock()

    def start(self):
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((HOST, PORT))
        server.listen(1)

        conn, _ = server.accept()

        with self.lock:
            self.client = conn

        buffer = ""

        while True:
            try:
                data = conn.recv(4096).decode("utf-8")
                if not data:
                    break

                buffer += data

                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)

                    if line.strip():
                        self.messages.put(json.loads(line))

            except Exception:
                break

    def send(self, payload):
        with self.lock:
            if not self.client:
                return

            try:
                self.client.sendall((json.dumps(payload) + "\n").encode("utf-8"))
            except Exception:
                pass

    def get_messages(self):
        out = []

        while not self.messages.empty():
            out.append(self.messages.get())

        return out


class ReachyInterview:
    def __init__(self):
        self.model = mujoco.MjModel.from_xml_path(str(MODEL_PATH))
        self.data = mujoco.MjData(self.model)

        self.condition = "empathetic"
        self.motion = "idle"
        self.question_index = -1
        self.awaiting_input = False
        self.next_question_time = None
        self.shutdown_requested = False

        self.start_time = time.time()

        self.overlay = OverlayServer()
        self.overlay.start()

        self.joint_ids = {}
        for name in [
            "yaw_body",
            "right_antenna",
            "left_antenna",
            "stewart_1",
            "stewart_2",
            "stewart_3",
            "stewart_4",
            "stewart_5",
            "stewart_6",
        ]:
            jid = mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_JOINT, name)

            if jid >= 0:
                self.joint_ids[name] = jid

    def launch_overlay(self):
        python_bin = Path(sys.prefix) / "bin" / "python"

        subprocess.Popen(
            [str(python_bin), "overlay_ui.py", str(PORT)],
            cwd=str(Path(__file__).parent),
        )

    def set_joint(self, name, value):
        if name not in self.joint_ids:
            return

        jid = self.joint_ids[name]
        qpos_addr = self.model.jnt_qposadr[jid]
        self.data.qpos[qpos_addr] = value

    def reset_pose(self):
        for name in self.joint_ids:
            self.set_joint(name, 0.0)

    def update_motion(self):
        t = time.time() - self.start_time

        if self.motion == "negative":
            self.set_joint("yaw_body", -0.18)
            self.set_joint("stewart_1", 0.01)
            self.set_joint("stewart_2", -0.01)
            self.set_joint("stewart_3", 0.008)
            self.set_joint("stewart_4", -0.008)
            self.set_joint("right_antenna", 0.25 * np.sin(t * 1.4))
            self.set_joint("left_antenna", -0.25 * np.sin(t * 1.4))

        elif self.motion == "positive":
            self.set_joint("yaw_body", 0.08 * np.sin(t * 2.0))
            self.set_joint("right_antenna", 0.35 * np.sin(t * 3.0))
            self.set_joint("left_antenna", 0.35 * np.sin(t * 3.0))

        else:
            self.reset_pose()

    def send_overlay(self, payload):
        self.overlay.send(payload)

    def robot_say(self, text, branch="neutral", awaiting_after_speech=False):
        self.awaiting_input = False

        self.send_overlay({
            "type": "speech_start",
            "condition": self.condition,
            "awaiting": False,
        })

        def on_subtitle(chunk):
            self.send_overlay({
                "type": "subtitle",
                "text": chunk,
                "condition": self.condition,
                "awaiting": False,
            })

        def on_done():
            self.awaiting_input = awaiting_after_speech

            self.send_overlay({
                "type": "speech_done",
                "text": text,
                "condition": self.condition,
                "awaiting": awaiting_after_speech,
            })

        speak_async(
            text=text,
            branch=branch,
            on_subtitle=on_subtitle,
            on_done=on_done,
        )

    def start_interview(self):
        self.question_index = -1
        self.next_question_time = None

        if self.condition == "empathetic":
            self.motion = "positive"
            self.robot_say(INTRO, "positive", awaiting_after_speech=True)
        else:
            self.motion = "idle"
            self.robot_say(INTRO, "neutral", awaiting_after_speech=True)

    def ask_next_question(self):
        self.question_index += 1

        if self.question_index >= len(QUESTIONS):
            if self.condition == "empathetic":
                self.motion = "positive"
                self.robot_say(OUTRO, "positive", awaiting_after_speech=False)
            else:
                self.motion = "idle"
                self.robot_say("Interview complete.", "neutral", awaiting_after_speech=False)

            return

        self.motion = "idle"
        self.robot_say(
            QUESTIONS[self.question_index]["question"],
            "neutral",
            awaiting_after_speech=True,
        )

    def submit_answer(self, text):
        if not self.awaiting_input:
            return

        text = text.strip()

        if not text:
            return

        self.awaiting_input = False

        if self.question_index == -1:
            self.ask_next_question()
            return

        item = QUESTIONS[self.question_index]
        branch = classify_answer(text)

        if self.condition == "neutral":
            self.motion = "idle"
            response = item["neutral"]
            self.robot_say(response, "neutral", awaiting_after_speech=False)

        elif branch == "negative":
            self.motion = "negative"
            response = f"{random.choice(BACKCHANNELS)} {item['negative']}"
            self.robot_say(response, "negative", awaiting_after_speech=False)

        elif branch == "positive":
            self.motion = "positive"
            response = item["positive"]
            self.robot_say(response, "positive", awaiting_after_speech=False)

        else:
            self.motion = "idle"
            response = "Thank you for sharing that with me. Let's continue."
            self.robot_say(response, "neutral", awaiting_after_speech=False)

        # Advance after the TTS finishes + small pause.
        self.next_question_time = None

        def delayed_next():
            time.sleep(0.6)
            self.next_question_time = time.time()

        threading.Thread(target=delayed_next, daemon=True).start()

    def set_condition(self, condition):
        if condition not in ["empathetic", "neutral"]:
            return

        self.condition = condition
        self.motion = "idle"

        self.send_overlay({
            "type": "status",
            "text": f"Condition set to {condition.upper()}.",
            "condition": self.condition,
            "awaiting": self.awaiting_input,
        })

    def handle_overlay_messages(self):
        for msg in self.overlay.get_messages():
            kind = msg.get("type")

            if kind == "start":
                self.start_interview()

            elif kind == "submit":
                self.submit_answer(msg.get("text", ""))

            elif kind == "condition":
                self.set_condition(msg.get("condition", "empathetic"))

            elif kind == "shutdown":
                self.shutdown_requested = True

    def maybe_advance(self):
        if self.next_question_time is not None and time.time() >= self.next_question_time:
            self.next_question_time = None
            self.ask_next_question()

    def run(self):
        self.launch_overlay()

        time.sleep(1.0)

        self.send_overlay({
            "type": "status",
            "text": "Press Start when ready.",
            "condition": self.condition,
            "awaiting": True,
        })

        with mujoco.viewer.launch_passive(
            self.model,
            self.data,
            show_left_ui=False,
            show_right_ui=False,
        ) as viewer:

            while viewer.is_running() and not self.shutdown_requested:
                self.handle_overlay_messages()
                self.maybe_advance()
                self.update_motion()

                mujoco.mj_step(self.model, self.data)
                viewer.sync()

                time.sleep(0.016)

        self.send_overlay({"type": "shutdown"})


if __name__ == "__main__":
    ReachyInterview().run()