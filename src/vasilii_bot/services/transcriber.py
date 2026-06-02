from pathlib import Path
from typing import Protocol

from openai import AsyncOpenAI

from ..config import Settings

PROVIDER_BASE_URLS = {
    "mashagpt": "https://api.mashagpt.ru/v1",
    "bothub": "https://openai.bothub.chat/v1",
    "proxyapi": "https://api.proxyapi.ru/openai/v1",
    "openai": None,
}


class TranscriptionError(RuntimeError):
    pass


class Transcriber(Protocol):
    async def transcribe(self, audio_path: Path) -> str:
        pass


class OpenAITranscriber:
    def __init__(self, api_key: str, model: str, base_url: str | None = None):
        if not api_key:
            raise TranscriptionError("OPENAI_API_KEY is required for voice transcription")

        client_kwargs = {"api_key": api_key}
        if base_url:
            client_kwargs["base_url"] = base_url

        self.client = AsyncOpenAI(**client_kwargs)
        self.model = model

    async def transcribe(self, audio_path: Path) -> str:
        with audio_path.open("rb") as audio_file:
            result = await self.client.audio.transcriptions.create(
                model=self.model,
                file=audio_file,
                language="ru",
            )
        text = getattr(result, "text", None)
        if not text:
            raise TranscriptionError("Transcription provider returned empty text")
        return str(text).strip()


def create_transcriber(settings: Settings) -> Transcriber:
    provider = settings.transcription_provider
    model = settings.openai_transcription_model or settings.transcription_model

    if provider == "custom":
        api_key = settings.transcription_api_key
        base_url = settings.transcription_base_url
    elif provider == "mashagpt":
        api_key = (
            settings.transcription_api_key
            or settings.mashagpt_api_key
            or settings.openai_api_key
        )
        base_url = settings.transcription_base_url or PROVIDER_BASE_URLS["mashagpt"]
    elif provider == "bothub":
        api_key = (
            settings.transcription_api_key
            or settings.bothub_api_key
            or settings.openai_api_key
        )
        base_url = settings.transcription_base_url or PROVIDER_BASE_URLS["bothub"]
    elif provider == "proxyapi":
        api_key = settings.transcription_api_key or settings.proxyapi_api_key
        base_url = settings.transcription_base_url or PROVIDER_BASE_URLS["proxyapi"]
    elif provider == "openai":
        api_key = settings.transcription_api_key or settings.openai_api_key
        base_url = settings.transcription_base_url or settings.openai_base_url
    else:
        raise TranscriptionError(f"Unsupported transcription provider: {provider}")

    if not api_key:
        raise TranscriptionError(f"Missing API key for transcription provider: {provider}")

    return OpenAITranscriber(
        api_key=api_key.get_secret_value(),
        model=model,
        base_url=base_url,
    )
