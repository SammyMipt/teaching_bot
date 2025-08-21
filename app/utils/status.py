from typing import Literal

SlotStatus = Literal["free", "closed", "canceled", "archived"]

FREE = "free"
CLOSED = "closed"
CANCELED = "canceled"
ARCHIVED = "archived"

ALL_STATUSES: tuple[SlotStatus, ...] = (FREE, CLOSED, CANCELED, ARCHIVED)
