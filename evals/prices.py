"""Per-model token prices for the eval's cost line. An estimate: list prices
read 2026-11-05 (USD per million tokens), standard 5-minute cache writes; a
model missing here is reported at $0 with its token counts, never guessed.
"""

from packages.core.agent.harness import Usage

# (input, output) per million tokens; cache reads bill at 0.1x input and
# 5-minute cache writes at 1.25x input on these models.
PRICES: dict[str, tuple[float, float]] = {
    "claude-haiku-4-5": (1.0, 5.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-opus-4-8": (5.0, 25.0),
}


def usd(usage: Usage) -> float:
    price = PRICES.get(usage["model"])
    if price is None:
        return 0.0
    per_in, per_out = price[0] / 1e6, price[1] / 1e6
    return (
        usage["input"] * per_in
        + usage["cache_read"] * per_in * 0.1
        + usage["cache_write"] * per_in * 1.25
        + usage["output"] * per_out
    )
