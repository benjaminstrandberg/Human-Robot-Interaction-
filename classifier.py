import os
from openai import OpenAI

client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))


def classify_answer_llm(answer):
    if not os.environ.get("OPENAI_API_KEY"):
        return None

    try:
        response = client.responses.create(
            model="gpt-4.1-mini",
            input=[
                {
                    "role": "system",
                    "content": (
                        "Classify a student's short answer in a wellbeing check-in. "
                        "Return exactly one word only: positive, negative, or unclear. "
                        "Negative includes stress, tiredness, poor sleep, loneliness, lack of time, isolation, anxiety, overwhelm, sadness, or struggle. "
                        "Positive includes feeling good, managing, support from friends/family, hobbies, rest, progress, or optimism."
                    ),
                },
                {
                    "role": "user",
                    "content": answer,
                },
            ],
            temperature=0,
            max_output_tokens=16,
        )

        label = response.output_text.strip().lower()

        if label in ["positive", "negative", "unclear"]:
            return label

        return None

    except Exception as e:
        print(f"[Classifier] LLM failed, falling back to keywords: {e}")
        return None