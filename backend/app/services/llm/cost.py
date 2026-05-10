from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TokenCost:
    model_id: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    prompt_unit_yuan: float = 0.0
    completion_unit_yuan: float = 0.0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    @property
    def yuan(self) -> float:
        return (
            self.prompt_tokens / 1000 * self.prompt_unit_yuan
            + self.completion_tokens / 1000 * self.completion_unit_yuan
        )


def estimate_embedding_cost(model_id: str, input_tokens: int, unit_yuan: float = 0.0) -> TokenCost:
    return TokenCost(model_id=model_id, prompt_tokens=input_tokens, prompt_unit_yuan=unit_yuan)
