import os
import base64
import json
from anthropic import Anthropic
from dotenv import load_dotenv
from symptom_checker import LANGUAGE_NAMES, CLAUDE_MODEL

load_dotenv()

_api_key = os.getenv("ANTHROPIC_API_KEY")
if not _api_key:
    raise RuntimeError("ANTHROPIC_API_KEY is not set. Refusing to start.")
client = Anthropic(api_key=_api_key)


def analyze_image_initial(image_bytes: bytes, image_type: str, additional_info: str = "", language: str = 'en') -> dict:
    """
    First call when a patient uploads a medical image.
    Describes what the AI observes and asks exactly ONE follow-up question.
    Returns {"type": "question", "text": "..."}
    """
    image_base64 = base64.standard_b64encode(image_bytes).decode("utf-8")
    lang_name = LANGUAGE_NAMES.get(language, 'English')

    extra = f"\nAdditional note from patient: {additional_info}" if additional_info else ""

    prompt = f"""You are a medical AI assistant acting like an attentive doctor during a consultation.
A patient has just uploaded a medical photo for you to examine.{extra}

IMPORTANT: Your entire response must be written in {lang_name}.

Your task:
1. Briefly describe what you observe in the image (2-3 sentences, clinical but warm and empathetic).
2. Ask exactly ONE follow-up question to gather more information before forming any diagnosis.
   Good questions cover: how long the condition has been present, pain or discomfort level (1-10),
   associated symptoms (fever, itching, swelling, discharge, etc.), or relevant personal or medical history.

Do NOT provide any diagnosis, urgency level, or treatment advice yet.
Respond in natural conversational text only — like a caring doctor who just looked at the photo and is now asking the patient a question."""

    message = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=512,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": image_type,
                            "data": image_base64,
                        },
                    },
                    {"type": "text", "text": prompt},
                ],
            }
        ],
    )

    text = message.content[0].text.strip()
    return {"type": "question", "text": text}


def image_chat_analyze(messages: list, language: str = 'en', exchange_count: int = 0) -> dict:
    """
    Continue the conversation that started with an image upload.
    The image observation is already captured in the conversation history.
    Returns {"type": "question", "text": "..."} until exchange_count >= 2 and enough info,
    then returns {"type": "diagnosis", "urgency": ..., "conditions": ..., "advice": ...}
    """
    lang_name = LANGUAGE_NAMES.get(language, 'English')

    system = f"""You are a medical AI assistant conducting a follow-up consultation after examining a patient's medical photo.
The conversation history contains your initial observation of the image and the patient's responses so far.

Behaviour rules:
- Ask exactly ONE question per turn — never multiple questions at once.
- Be warm, empathetic, and thorough — like a doctor building a complete clinical picture.
- The patient has responded {exchange_count} time(s) since the image was submitted.
- Do NOT provide a diagnosis until the patient has responded at least 2 times AND you have sufficient clinical detail.
- For follow-up questions: respond in plain natural conversational text only — no JSON, no bullet points.
- Once you have sufficient information AND the patient has responded at least 2 times, respond with ONLY this valid JSON (no markdown, no code fences, no extra text):
{{
  "urgency": "low" | "medium" | "high",
  "conditions": "comma-separated list of possible conditions in {lang_name}",
  "advice": "bullet-point recommendations in {lang_name}, one per line starting with -"
}}
- The "urgency" value MUST always be exactly one of: "low", "medium", or "high" — always in English, regardless of the response language.
- The "conditions" and "advice" values must be written in {lang_name}.
- Always include in the advice that this is not a substitute for professional medical advice.
- Respond entirely in {lang_name}, except the urgency value which must stay in English."""

    response = client.messages.create(
        model=CLAUDE_MODEL,
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
