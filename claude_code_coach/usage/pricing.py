"""Published Anthropic API pricing — used only to turn real, locally-observed
token counts into an *estimated* dollar figure. Never used to invent token
counts; those always come from claude_code_coach/usage/transcript_parser.py,
which reads them directly out of Claude Code's own local session logs.

Source: https://claude.com/pricing (fetched 2026-09-11) and
https://platform.claude.com/docs/en/build-with-claude/prompt-caching for the
cache write/read multipliers. Prices are per-model, in USD per million
tokens, and can go stale if Anthropic changes them — PRICING_AS_OF exists so
the UI can say exactly how current this table is, rather than imply a live
billing feed.

A model not in MODEL_PRICING is never assigned a guessed price — callers
must treat its tokens as real but cost-unknown (see usage_analyzer.py's
`unpriced_tokens`).
"""

from __future__ import annotations

from dataclasses import dataclass

PRICING_AS_OF = "2026-09-11"
PRICING_SOURCE_URL = "https://claude.com/pricing"

# Cache pricing is a fixed multiplier of the base input price — confirmed
# against Anthropic's documented formula, not independently guessed:
#   5-minute cache write = 1.25x base input price
#   1-hour cache write   = 2x base input price
#   cache read            = 0.1x base input price
CACHE_WRITE_5M_MULTIPLIER = 1.25
CACHE_WRITE_1H_MULTIPLIER = 2.0
CACHE_READ_MULTIPLIER = 0.1


@dataclass(frozen=True)
class ModelPrice:
    input_per_mtok: float
    output_per_mtok: float

    @property
    def cache_write_5m_per_mtok(self) -> float:
        return self.input_per_mtok * CACHE_WRITE_5M_MULTIPLIER

    @property
    def cache_write_1h_per_mtok(self) -> float:
        return self.input_per_mtok * CACHE_WRITE_1H_MULTIPLIER

    @property
    def cache_read_per_mtok(self) -> float:
        return self.input_per_mtok * CACHE_READ_MULTIPLIER


# Real, current model IDs as they appear in Claude Code's own transcripts
# (message.model) — matched exactly, no fuzzy/prefix matching, so a renamed
# or future model is simply "unpriced" rather than silently mispriced.
MODEL_PRICING: dict[str, ModelPrice] = {
    "claude-sonnet-5": ModelPrice(input_per_mtok=2.0, output_per_mtok=10.0),
    "claude-opus-5": ModelPrice(input_per_mtok=5.0, output_per_mtok=25.0),
    "claude-haiku-4-5-20251001": ModelPrice(input_per_mtok=1.0, output_per_mtok=5.0),
    "claude-haiku-4.5": ModelPrice(input_per_mtok=1.0, output_per_mtok=5.0),
    "claude-fable-5-1": ModelPrice(input_per_mtok=10.0, output_per_mtok=50.0),
}


def price_for_model(model: str) -> ModelPrice | None:
    return MODEL_PRICING.get(model)


def estimate_cost_usd(
    model: str, *, input_tokens: int, output_tokens: int,
    cache_read_tokens: int, cache_write_5m_tokens: int, cache_write_1h_tokens: int,
) -> float | None:
    """Returns None (never 0.0) when the model isn't in MODEL_PRICING — a
    caller must not treat that as "free"."""
    price = price_for_model(model)
    if price is None:
        return None
    mtok = 1_000_000
    return (
        input_tokens / mtok * price.input_per_mtok
        + output_tokens / mtok * price.output_per_mtok
        + cache_read_tokens / mtok * price.cache_read_per_mtok
        + cache_write_5m_tokens / mtok * price.cache_write_5m_per_mtok
        + cache_write_1h_tokens / mtok * price.cache_write_1h_per_mtok
    )
