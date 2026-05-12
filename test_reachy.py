import os
import asyncio
from google import genai
import edge_tts
from playsound import playsound

# ---------- Gemini setup ----------

client = genai.Client(
    api_key=os.environ["GEMINI_API_KEY"]
)

# ---------- Emotion detection ----------

def detect_emotion(text):
    text = text.lower()

    if any(word in text for word in ["sad", "depressed", "lonely", "down"]):
        return "sad"

    if any(word in text for word in ["stressed", "anxious", "overwhelmed"]):
        return "stressed"

    if any(word in text for word in ["happy", "great", "excited"]):
        return "happy"

    return "neutral"


# ---------- TTS ----------

VOICE = "en-US-AriaNeural"

async def speak(text, emotion):

    if emotion == "sad":
        rate = "-20%"
        pitch = "-4Hz"

    elif emotion == "stressed":
        rate = "-10%"
        pitch = "-2Hz"

    elif emotion == "happy":
        rate = "+8%"
        pitch = "+2Hz"

    else:
        rate = "+0%"
        pitch = "+0Hz"

    communicate = edge_tts.Communicate(
        text=text,
        voice=VOICE,
        rate=rate,
        pitch=pitch
    )

    await communicate.save("speech.mp3")

    playsound("speech.mp3")


# ---------- Main loop ----------

while True:

    user_input = input("\nYou: ")

    if user_input.lower() in ["quit", "exit"]:
        break

    emotion = detect_emotion(user_input)

    prompt = f"""
    You are a supportive social robot for a university HRI project.

    Keep responses:
    - warm
    - short
    - emotionally supportive
    - conversational

    Never:
    - diagnose mental illness
    - give medical advice
    - claim to be a therapist

    User emotion: {emotion}

    User said:
    "{user_input}"
    """

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt
    )

    reply = response.text.strip()

    print(f"\nReachy: {reply}")

    asyncio.run(speak(reply, emotion))

