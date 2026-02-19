import logging

from google import genai

from src.config import GEMINI_MODEL, GOOGLE_API_KEY

logger = logging.getLogger(__name__)

_client: genai.Client | None = None


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        if not GOOGLE_API_KEY:
            raise ValueError("GOOGLE_API_KEY is not set. Add it to your .env file.")
        _client = genai.Client(api_key=GOOGLE_API_KEY)
    return _client


def generate(prompt: str, system_instruction: str = "") -> str:
    client = _get_client()

    logger.info("Calling Gemini (%s)", GEMINI_MODEL)

    config = None
    if system_instruction:
        config = genai.types.GenerateContentConfig(
            system_instruction=system_instruction,
        )

    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=prompt,
        config=config,
    )

    return response.text
