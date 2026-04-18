import os
import json
from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv()

client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

LANGUAGE_NAMES = {
    'en':   'English',
    'fr':   'French',
    'es':   'Spanish',
    'zh':   'Chinese',
    'de':   'German',
    'ar':   'Arabic',
}

def analyze_symptoms(symptoms: str, age: int = None, gender: str = None, language: str = "en") -> str:
    age_line    = f"- Age: {age}" if age else ""
    gender_line = f"- Gender: {gender}" if gender else ""
    patient_info = "\n".join(filter(None, [age_line, gender_line, f"- Symptoms: {symptoms}"]))
    lang_name = LANGUAGE_NAMES.get(language, 'English')

    prompt = f"""You are a helpful medical AI assistant. A patient has described the following symptoms:

Patient info:
{patient_info}

IMPORTANT: Your entire response must be written in {lang_name}. All fields — urgency, conditions, and advice — must be in {lang_name}.

Respond with ONLY a valid JSON object — no markdown, no explanation, just the JSON — using exactly these keys:
{{
  "urgency": "low" | "medium" | "high"  (use the equivalent word in {lang_name}),
  "conditions": "comma-separated list of possible conditions in {lang_name}",
  "advice": "bullet-point recommendations in {lang_name}, one per line starting with -"
}}

Always remind the patient in the advice field that this is not a substitute for professional medical advice (in {lang_name}).
"""

    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}]
    )

    raw = message.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {
            "urgency": "medium",
            "conditions": raw,
            "advice": "- Please consult a doctor for proper diagnosis.\n- This is not a substitute for professional medical advice."
        }
