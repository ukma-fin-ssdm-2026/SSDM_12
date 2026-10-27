"""Шаблон маршруту для журналу доступу."""

import uuid


def route_template(path: str) -> str:
    """Замінює сегменти з канонічним UUID на {id}."""
    segments = []
    for segment in path.split("/"):
        try:
            canonical = str(uuid.UUID(segment)) == segment.lower()
        except ValueError:
            canonical = False
        segments.append("{id}" if canonical else segment)
    return "/".join(segments)
