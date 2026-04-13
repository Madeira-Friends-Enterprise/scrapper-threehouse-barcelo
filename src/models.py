from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone


HEADER = [
    "scraped_at",
    "brand",
    "hotel_name",
    "hotel_id",
    "city",
    "date",
    "price",
    "currency",
    "available",
    "min_stay",
    "source_url",
]


@dataclass
class PriceRow:
    brand: str
    hotel_name: str
    hotel_id: str
    city: str
    date: date
    price: float | None
    currency: str = "EUR"
    available: bool = True
    min_stay: int | None = None
    source_url: str = ""
    scraped_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_row(self) -> list:
        return [
            self.scraped_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
            self.brand,
            self.hotel_name,
            self.hotel_id,
            self.city,
            self.date.isoformat(),
            "" if self.price is None else f"{self.price:.2f}",
            self.currency,
            "TRUE" if self.available else "FALSE",
            "" if self.min_stay is None else self.min_stay,
            self.source_url,
        ]
