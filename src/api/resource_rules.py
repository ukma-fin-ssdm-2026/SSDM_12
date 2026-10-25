"""Lab6 prepared reference: resource_rules.py. AI-assisted draft."""

from api.enums import ResourceType

MIN_CAPACITY = 1
MAX_CAPACITY = 1000


def capacity_valid(kind: ResourceType, capacity: object) -> bool:
    """INV-08: room = integer 1..1000; consultation = no capacity (bool is not int)."""
    if kind is ResourceType.ROOM:
        return (
            isinstance(capacity, int)
            and not isinstance(capacity, bool)
            and MIN_CAPACITY <= capacity <= MAX_CAPACITY
        )
    return kind is ResourceType.CONSULTATION and capacity is None
