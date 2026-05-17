QUESTIONS = [
    {
        "question": "To start, how would you describe your general mood and feelings over the past few days? Have you been feeling mostly positive or a bit down?",
        "negative": "I hear you. It is completely normal to have low moments, especially with everything you have going on. Thank you for sharing that with me.",
        "positive": "I am so glad to hear that! It is wonderful that you are keeping a positive mindset lately.",
        "neutral": "Understood. Mood status logged. Moving to the next question."
    },
    {
        "question": "First, let's talk about your studies. How have you been feeling regarding your university workload and stress levels this week?",
        "negative": "I am really sorry to hear that. University workload can be incredibly heavy and exhausting. Please remember to take short breaks.",
        "positive": "That is wonderful to hear! Managing university stress is tough, so you should be proud of yourself.",
        "neutral": "Understood. Data recorded. Let's move on to the next question."
    },
    {
        "question": "It is important to disconnect. Have you been able to find time for your personal interests or hobbies outside of class?",
        "negative": "I see. It is easy to lose track of our hobbies when things get busy. Try to secure even just 10 minutes tomorrow for something you enjoy.",
        "positive": "Excellent! Keeping up with your activities is a great way to protect your mental health.",
        "neutral": "Acknowledged. Proceeding to the final question."
    },
    {
        "question": "Lastly, human connection matters. Have you been in touch with your family or close friends recently?",
        "negative": "I understand. Sometimes we isolate ourselves when stressed, but reaching out to loved ones can really lighten the burden. Maybe send them a quick text later?",
        "positive": "That is great! Having a strong support system is key. I'm glad you are staying connected.",
        "neutral": "Response noted. The interview is now complete."
    }
]

NEGATIVE_KEYWORDS = [
    "sad", "down", "bad", "low", "depressed", "negative",
    "stressed", "overwhelmed", "tired", "struggling", "anxious",
    "no", "not really", "no time", "too busy", "none",
    "isolated", "lonely", "not much", "neglected"
]

POSITIVE_KEYWORDS = [
    "positive", "good", "happy", "great", "well", "fine",
    "managing", "okay", "chilling",
    "yes", "yeah", "some", "a bit", "played", "went out",
    "called", "talked", "saw them", "texted", "excellent"
]

BACKCHANNELS = [
    "Oh, I see...",
    "Mhm, I understand...",
    "I hear you..."
]

INTRO = (
    "Hi there! I am your weekly wellbeing assistant. "
    "It is time for our quick check-in to see how you've been managing your university life lately. "
    "Shall we begin?"
)

OUTRO = (
    "Thank you for completing your weekly check-in. "
    "Your reflection today is a great step toward caring for your mental health. "
    "Have a steady week ahead!"
)