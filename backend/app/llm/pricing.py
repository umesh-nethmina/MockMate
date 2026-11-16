"""US$ per million tokens: (input, output, cache read, cache write). Update when Anthropic pricing changes."""

PRICES: dict[str, tuple[float, float, float, float]] = {
    "claude-opus-5-5": (4.00, 20.00, 0.20, 5.00),
    "claude-opus-5": (5.00, 25.00, 0.50, 6.25),
    "claude-opus-4-8": (5.00, 25.00, 0.50, 6.25),
    "claude-sonnet-5-5": (2.00, 10.00, 0.10, 2.50),
    "claude-haiku-5-5": (0.10, 0.50, 0.01, 0.125),
}
DEFAULT_MODEL = "claude-opus-5-5"


def cost_usd(model: str, input_tokens: int, output_tokens: int, cache_read: int, cache_write: int) -> float:
    p_in, p_out, p_read, p_write = PRICES.get(model, PRICES[DEFAULT_MODEL])
    total = input_tokens * p_in + output_tokens * p_out + cache_read * p_read + cache_write * p_write
    return round(total / 1_000_000, 6)
