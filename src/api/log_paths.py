"""Шаблон маршруту для журналу доступу."""

_HEX_AND_DASH = set("0123456789abcdef-")


def route_template(path: str) -> str:
    """Замінює 36-символьні hex-сегменти шляху на {id}, без огляду на регістр."""
    segments = []
    for segment in path.split("/"):
        if len(segment) == 36 and set(segment.lower()) <= _HEX_AND_DASH:
            segments.append("{id}")
        else:
            segments.append(segment)
    return "/".join(segments)
