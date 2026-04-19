import os
import base64
from anthropic import Anthropic
from dotenv import load_dotenv
from symptom_checker import LANGUAGE_NAMES

load_dotenv()

client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))


def analyze_image(image_bytes: bytes, image_type: str, additional_info: str = "", language: str = 'en') -> str:
    image_base64 = base64.standard_b64encode(image_bytes).decode("utf-8")
    lang_name = LANGUAGE_NAMES.get(language, 'English')

    prompt = f"""You are a medical AI assistant helping patients in underserved communities.

A patient has uploaded a medical image for analysis.
Additional information from patient: {additional_info if additional_info else "None provided"}

IMPORTANT: Your entire response must be written in {lang_name}.

Please analyze this image and provide (in {lang_name}):
1. What you observe in the image
2. Possible conditions this could indicate
3. Urgency level (low / medium / high — translated to {lang_name})
4. Recommended next steps
5. Whether they should see a doctor immediately

Always remind the patient this is not a substitute for professional medical advice (in {lang_name}).
"""

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
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
                    {"type": "text", "text": prompt}
                ],
            }
        ],
    )

    return message.content[0].text
