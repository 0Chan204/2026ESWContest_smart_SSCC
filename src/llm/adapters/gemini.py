from __future__ import annotations

import os

from google import genai
from google.genai import types

from .base import BaseLLMAdapter


class GeminiAdapter(BaseLLMAdapter):
    name = "gemini-2.5-flash"

    def __init__(
        self,
        model_name: str = "gemini-2.5-flash",
        temperature: float = 0.3,
    ) -> None:
        self.model_name = model_name
        self.temperature = temperature

        project = os.getenv("GOOGLE_CLOUD_PROJECT")
        location = os.getenv("GOOGLE_CLOUD_LOCATION", "global")

        if not project:
            raise RuntimeError(
                "GOOGLE_CLOUD_PROJECT environment variable is not set."
            )

        self.client = genai.Client(
            vertexai=True,
            project=project,
            location=location,
        )

    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
    ) -> str:

        response = self.client.models.generate_content(
            model=self.model_name,
            contents=user_prompt,
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                temperature=self.temperature,
            ),
        )

        if not response.text:
            raise RuntimeError("Gemini returned an empty response.")

        return response.text.strip()