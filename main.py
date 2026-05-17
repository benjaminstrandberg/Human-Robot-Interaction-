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

from classifier import classify_answer_llm

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
    
    llm_label = classify_answer_llm(text);
    
    if llm_label is not None:
        print(f"[Classifier] LLM Label: {llm_label}")
        return llm_label
    
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
        self.motion_start_time = time.time()

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

    def set_motion(self, motion):
        self.motion = motion
        self.motion_start_time = time.time()

    def elapsed_motion(self):
        return time.time() - self.motion_start_time

    def set_joint(self, name, value):
        if name not in self.joint_ids:
            return

        jid = self.joint_ids[name]
        qpos_addr = self.model.jnt_qposadr[jid]
        self.data.qpos[qpos_addr] = value

    def reset_pose(self):
        for name in self.joint_ids:
            self.set_joint(name, 0.0)

    def smoothstep(self, x):
        x = max(0.0, min(1.0, x))
        return x * x * (3.0 - 2.0 * x)

    def damped_sine(self, t, speed=1.0, decay=1.0):
        return np.sin(t * np.pi * 2.0 * speed) * np.exp(-t * decay)

    def apply_head_platform(self, pitch=0.0, roll=0.0):
        """
        Approximate pitch/roll using Reachy Mini's Stewart-platform joints.
        Values are deliberately in a visible-but-not-insane range.
        """
        self.set_joint("stewart_1", 0.050 * pitch + 0.035 * roll)
        self.set_joint("stewart_2", 0.050 * pitch - 0.035 * roll)
        self.set_joint("stewart_3", -0.040 * pitch + 0.035 * roll)
        self.set_joint("stewart_4", -0.040 * pitch - 0.035 * roll)
        self.set_joint("stewart_5", 0.028 * pitch)
        self.set_joint("stewart_6", -0.028 * pitch)

    def neutral_pose(self):
        """
        Condition 2:
        Cold mechanical baseline.
        Direct gaze, no antennas, no head motion.
        """
        self.reset_pose()

    def question_pose(self):
        """
        Empathetic condition while asking questions:
        mostly neutral/direct, but with tiny life.
        Keeps attention on the question instead of emotional reaction.
        """
        t = self.elapsed_motion()
        self.reset_pose()

        self.set_joint("yaw_body", 0.015 * np.sin(t * 0.7))
        self.apply_head_platform(
            pitch=0.04 * np.sin(t * 0.9),
            roll=0.025 * np.sin(t * 0.6),
        )

        self.set_joint("right_antenna", 0.035 * np.sin(t * 0.9))
        self.set_joint("left_antenna", 0.035 * np.sin(t * 0.9 + 0.2))

    def intro_positive_pose(self):
        """
        Script: big smile + slight head nod.
        We approximate face with a friendly greeting nod and warm antenna lift.
        """
        t = self.elapsed_motion()
        self.reset_pose()

        nod = self.damped_sine(t, speed=0.95, decay=0.85)

        self.set_joint("yaw_body", 0.025 * np.sin(t * 0.8))
        self.apply_head_platform(
            pitch=0.95 * nod,
            roll=0.04 * np.sin(t * 0.8),
        )

        antenna_base = 0.10
        antenna_bounce = 0.16 * self.damped_sine(t, speed=1.0, decay=0.7)
        self.set_joint("right_antenna", antenna_base + antenna_bounce)
        self.set_joint("left_antenna", antenna_base + antenna_bounce)

    def positive_response_pose(self):
        """
        Positive branch:
        - one/two readable encouraging nods
        - then settles into attentive stillness
        - antennas lift briefly, then calm down
        """
        t = self.elapsed_motion()
        self.reset_pose()

        if t < 2.4:
            nod = self.damped_sine(t, speed=1.15, decay=0.9)
            pitch = 1.15 * nod
            antenna = 0.22 * self.damped_sine(t, speed=1.05, decay=0.65)
        else:
            pitch = 0.03 * np.sin(t * 0.45)
            antenna = 0.025 * np.sin(t * 0.45)

        self.set_joint("yaw_body", 0.025 * np.sin(t * 0.55))
        self.apply_head_platform(
            pitch=pitch,
            roll=0.035 * np.sin(t * 0.5),
        )

        self.set_joint("right_antenna", antenna)
        self.set_joint("left_antenna", antenna)

    def negative_response_pose(self):
        """
        Negative branch:
        - slow gaze aversion
        - head lowers and tilts to side
        - holds stillness while speaking
        - antennas move very slowly, not cheerfully
        """
        t = self.elapsed_motion()
        self.reset_pose()

        ease = self.smoothstep(t / 1.15)

        # Main expressive cue: look away and slightly down/side.
        self.set_joint("yaw_body", -0.36 * ease)

        # Hold a clear concerned pose after easing in.
        base_pitch = -0.95 * ease
        base_roll = 0.70 * ease

        # Tiny breathing only, so it doesn't look robotic-wiggly.
        breath = 0.025 * np.sin(t * 0.55)

        self.apply_head_platform(
            pitch=base_pitch + breath,
            roll=base_roll,
        )

        # Slow asymmetric antennas: engaged, not excited.
        self.set_joint("right_antenna", 0.10 * np.sin(t * 0.55))
        self.set_joint("left_antenna", -0.10 * np.sin(t * 0.55 + 0.45))

    def unclear_pose(self):
        """
        Mild attentive pause for unclear answers.
        """
        t = self.elapsed_motion()
        self.reset_pose()

        self.set_joint("yaw_body", 0.04 * np.sin(t * 0.5))
        self.apply_head_platform(
            pitch=0.10 * np.sin(t * 0.55),
            roll=0.03 * np.sin(t * 0.4),
        )

        self.set_joint("right_antenna", 0.04 * np.sin(t * 0.7))
        self.set_joint("left_antenna", 0.04 * np.sin(t * 0.7 + 0.3))

    def outro_positive_pose(self):
        """
        Outro:
        polite final nod, then returns toward idle friendliness.
        """
        t = self.elapsed_motion()
        self.reset_pose()

        if t < 2.0:
            nod = self.damped_sine(t, speed=0.8, decay=0.8)
            pitch = 0.85 * nod
            antenna = 0.13 * self.damped_sine(t, speed=0.8, decay=0.7)
        else:
            pitch = 0.02 * np.sin(t * 0.4)
            antenna = 0.02 * np.sin(t * 0.4)

        self.set_joint("yaw_body", 0.02 * np.sin(t * 0.45))
        self.apply_head_platform(
            pitch=pitch,
            roll=0.025 * np.sin(t * 0.4),
        )

        self.set_joint("right_antenna", antenna)
        self.set_joint("left_antenna", antenna)

    def update_motion(self):
        if self.condition == "neutral":
            self.neutral_pose()
            return

        if self.motion == "intro_positive":
            self.intro_positive_pose()

        elif self.motion == "question":
            self.question_pose()

        elif self.motion == "positive":
            self.positive_response_pose()

        elif self.motion == "negative":
            self.negative_response_pose()

        elif self.motion == "unclear":
            self.unclear_pose()

        elif self.motion == "outro_positive":
            self.outro_positive_pose()

        else:
            self.neutral_pose()

    def send_overlay(self, payload):
        self.overlay.send(payload)

    def robot_say(self, text, branch="neutral", awaiting_after_speech=False, after_done=None):
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

            if after_done:
                after_done()

        speak_async(
            text=text,
            branch=branch,
            on_subtitle=on_subtitle,
            on_done=on_done,
        )

    def schedule_next_question(self):
        self.next_question_time = time.time() + 0.65

    def start_interview(self):
        self.question_index = -1
        self.next_question_time = None

        if self.condition == "empathetic":
            self.set_motion("intro_positive")
            self.robot_say(INTRO, "positive", awaiting_after_speech=True)
        else:
            self.set_motion("idle")
            self.robot_say(INTRO, "neutral", awaiting_after_speech=True)

    def ask_next_question(self):
        self.question_index += 1

        if self.question_index >= len(QUESTIONS):
            if self.condition == "empathetic":
                self.set_motion("outro_positive")
                self.robot_say(OUTRO, "positive", awaiting_after_speech=False)
            else:
                self.set_motion("idle")
                self.robot_say("Interview complete.", "neutral", awaiting_after_speech=False)
            return

        if self.condition == "empathetic":
            self.set_motion("question")
        else:
            self.set_motion("idle")

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
        self.next_question_time = None

        if self.question_index == -1:
            self.ask_next_question()
            return

        item = QUESTIONS[self.question_index]
        branch = classify_answer(text)

        if self.condition == "neutral":
            self.set_motion("idle")
            response = item["neutral"]
            response_branch = "neutral"

        elif branch == "negative":
            self.set_motion("negative")
            response = f"{random.choice(BACKCHANNELS)} {item['negative']}"
            response_branch = "negative"

        elif branch == "positive":
            self.set_motion("positive")
            response = item["positive"]
            response_branch = "positive"

        else:
            self.set_motion("unclear")
            response = "Thank you for sharing that with me. Let's continue."
            response_branch = "neutral"

        self.robot_say(
            response,
            response_branch,
            awaiting_after_speech=False,
            after_done=self.schedule_next_question,
        )

    def set_condition(self, condition):
        if condition not in ["empathetic", "neutral"]:
            return

        self.condition = condition
        self.set_motion("idle")

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