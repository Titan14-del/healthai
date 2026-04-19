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

def chat_analyze(messages: list, age: int = None, gender: str = None, language: str = "en") -> dict:
    """
    Multi-turn conversational intake.
    Returns {"type": "question", "text": "..."} or {"type": "diagnosis", "urgency": ..., "conditions": ..., "advice": ...}
    """
    lang_name = LANGUAGE_NAMES.get(language, 'English')

    age_line    = f"- Age: {age}" if age else ""
    gender_line = f"- Gender: {gender}" if gender else ""
    profile_parts = list(filter(None, [age_line, gender_line]))
    profile_note  = ("\n\nPatient profile:\n" + "\n".join(profile_parts)) if profile_parts else ""

    system = f"""You are HealthAI, a clinically trained medical AI conducting a structured patient intake interview.

Your goal is to gather enough clinical detail to give a medically accurate preliminary assessment. Ask follow-up questions ONE AT A TIME in this order as relevant:
1. Duration — how long have the symptoms been present?
2. Severity — rate discomfort 1–10; describe character (sharp, dull, throbbing, burning, pressure)
3. Location — exact location; does it radiate or move elsewhere?
4. Associated symptoms — fever, nausea, vomiting, fatigue, shortness of breath, or other symptoms?

Rules:
- Ask only ONE focused clinical question per turn.
- Keep questions concise and conversational.
- After 3–4 exchanges (or sooner if the clinical picture is clear), provide the final assessment.
- For follow-up questions: respond in plain text only — one question, nothing else.
- For the final assessment: respond with ONLY valid JSON (no markdown, no code fences, no explanation):
{{
  "urgency": "low" | "medium" | "high",
  "conditions": "comma-separated list of possible conditions",
  "advice": "bullet-point medical recommendations, one per line starting with -"
}}
- Always include in the advice that this is not a substitute for professional medical advice.
- Respond entirely in {lang_name}.{profile_note}"""

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1024,
        system=system,
        messages=messages,
    )

    raw = response.content[0].text.strip()

    # Strip markdown code fences if present
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    # Try to parse as final diagnosis JSON
    try:
        parsed = json.loads(raw)
        if all(k in parsed for k in ("urgency", "conditions", "advice")):
            return {"type": "diagnosis", **parsed}
    except (json.JSONDecodeError, ValueError):
        pass

    # Otherwise it's a follow-up question
    return {"type": "question", "text": raw}
