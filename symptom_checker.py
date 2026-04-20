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

def generate_title(messages: list, conditions: str = "") -> str:
    """Generate a concise 3-5 word consultation title from the conversation."""
    user_msgs = [m["content"] for m in messages if m.get("role") == "user"][:3]
    context   = " | ".join(user_msgs)
    prompt    = (
        "Generate a concise 3-5 word medical consultation title based on this context.\n"
        "Format examples: \"Headache and Fever\", \"Chest Pain Evaluation\", \"Lower Back Pain\"\n"
        f"Conversation: {context}\n"
        f"Conditions: {conditions}\n\n"
        "Respond with ONLY the title text — no quotes, no trailing punctuation."
    )
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=20,
        messages=[{"role": "user", "content": prompt}]
    )
    return message.content[0].text.strip()[:60]


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
        model="claude-sonnet-4-6",
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

    user_turns = sum(1 for m in messages if m.get("role") == "user")

    system = f"""You are a friendly medical AI assistant. Have a natural conversation to understand the patient's symptoms before diagnosing. Ask one question at a time.

Behaviour rules:
- If the patient greets you (e.g. "hey", "hello", "hi", "good morning"), greet them warmly and ask what symptoms they are experiencing today.
- Ask exactly ONE question per turn — never multiple questions at once.
- Be warm, empathetic, and clear — like a caring doctor in a consultation.
- Gather information naturally across the conversation: what symptoms, how long, severity (1–10), location, and any associated symptoms (fever, nausea, fatigue, etc.).
- The patient has sent {user_turns} message(s) so far in this conversation.
- Do NOT provide a diagnosis until the patient has sent at least 3 messages AND you have enough clinical detail to do so responsibly.
- For all conversational replies (greetings, questions, clarifications): respond in plain natural text only.
- Once you have sufficient information AND at least 3 patient messages, respond with ONLY this valid JSON (no markdown, no code fences, no extra text):
{{
  "urgency": "low" | "medium" | "high",
  "conditions": "comma-separated list of possible conditions",
  "advice": "bullet-point recommendations, one per line starting with -"
}}
- Always include in the advice that this is not a substitute for professional medical advice.
- Respond entirely in {lang_name}.{profile_note}"""

    response = client.messages.create(
        model="claude-sonnet-4-6",
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
