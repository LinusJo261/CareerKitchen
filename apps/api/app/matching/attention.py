"""Legacy scale-adaptive attention and congestion dual updates, in routing units."""

from dataclasses import dataclass
from math import sqrt

from .types import finite


@dataclass(frozen=True, slots=True)
class MarketPrices:
    mu_candidate: float = 0.0
    mu_employer: float = 0.0
    job_congestion: float = 0.0
    candidate_congestion: float = 0.0
    version: str = "prices-v1"

    def __post_init__(self) -> None:
        for name in ("mu_candidate", "mu_employer", "job_congestion", "candidate_congestion"):
            finite(getattr(self, name), name)


@dataclass(frozen=True, slots=True)
class DualPrice:
    price: float = 0.0
    gradient_sum_sq: float = 0.0

    def __post_init__(self) -> None:
        finite(self.price, "price")
        finite(self.gradient_sum_sq, "gradient_sum_sq")


def update_price(
    previous: DualPrice,
    observed_load: float,
    capacity: float,
    minimum: float = 0.0,
    maximum: float = 10.0,
) -> DualPrice:
    """g=(A-B)/max(B,1), H+=g², mu=clamp(mu+g/sqrt(H+1))."""
    for name, value in (
        ("observed_load", observed_load),
        ("capacity", capacity),
        ("minimum", minimum),
        ("maximum", maximum),
    ):
        finite(value, name)
    if minimum > maximum:
        raise ValueError("minimum must not exceed maximum")
    gradient = (observed_load - capacity) / max(capacity, 1.0)
    history = previous.gradient_sum_sq + gradient * gradient
    return DualPrice(min(maximum, max(minimum, previous.price + gradient / sqrt(history + 1))), history)


# Congestion has exactly the same legacy dual update, with pending load/processing capacity.
update_congestion = update_price
