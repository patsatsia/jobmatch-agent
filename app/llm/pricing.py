from dataclasses import dataclass
from decimal import Decimal

PER_MTOK = Decimal(1_000_000)


@dataclass(frozen=True)
class ModelPrice:
    input: Decimal  # USD per million input tokens
    output: Decimal  # USD per million output tokens
    long_prompt_threshold: int | None = None
    long_input: Decimal | None = None
    long_output: Decimal | None = None


PRICES: dict[str, ModelPrice] = {
    "claude-haiku-5-5": ModelPrice(
        input=Decimal("0.10"),
        output=Decimal("0.50"),
        long_prompt_threshold=100_000,
        long_input=Decimal("0.50"),
        long_output=Decimal("2.50"),
    ),
    "claude-sonnet-5-5": ModelPrice(input=Decimal("2"), output=Decimal("10")),
}


def cost_usd(model: str, input_tokens: int, output_tokens: int) -> Decimal:
    price = PRICES[model]
    in_rate, out_rate = price.input, price.output
    if price.long_prompt_threshold and input_tokens > price.long_prompt_threshold:
        in_rate, out_rate = price.long_input or in_rate, price.long_output or out_rate
    return (input_tokens * in_rate + output_tokens * out_rate) / PER_MTOK
