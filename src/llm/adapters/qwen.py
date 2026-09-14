from __future__ import annotations

from pathlib import Path

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

from .base import BaseLLMAdapter


class QwenAdapter(BaseLLMAdapter):
    name = "qwen3-8b"

    def __init__(
        self,
        model_path: str | None = None,
        max_new_tokens: int = 128,
    ) -> None:
        self.model_path = model_path or str(
            Path.home() / "models" / "Qwen3-8B"
        )
        self.max_new_tokens = max_new_tokens

        print(f"[Qwen] Loading local model: {self.model_path}")

        self.tokenizer = AutoTokenizer.from_pretrained(
            self.model_path,
            local_files_only=True,
            trust_remote_code=True,
        )

        self.model = AutoModelForCausalLM.from_pretrained(
            self.model_path,
            torch_dtype="auto",
            device_map="auto",
            local_files_only=True,
            trust_remote_code=True,
        )

        self.model.eval()

        print("[Qwen] Model loaded.")

    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
    ) -> str:

        messages = [
            {
                "role": "system",
                "content": system_prompt,
            },
            {
                "role": "user",
                "content": user_prompt,
            },
        ]

        text = self.tokenizer.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True,
            enable_thinking=False,
        )

        model_inputs = self.tokenizer(
            text,
            return_tensors="pt",
        ).to(self.model.device)

        with torch.no_grad():
            generated_ids = self.model.generate(
                **model_inputs,
                max_new_tokens=self.max_new_tokens,
                do_sample=True,
                temperature=0.7,
                top_p=0.8,
                top_k=20,
            )

        output_ids = generated_ids[0][
            model_inputs["input_ids"].shape[1]:
        ]

        response = self.tokenizer.decode(
            output_ids,
            skip_special_tokens=True,
        )

        return response.strip()