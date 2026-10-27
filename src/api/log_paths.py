"""Шаблон маршруту для журналу доступу.

Журнал доступу пише шлях запиту. Конкретний шлях містить ідентифікатори
(`/api/v1/bookings/3fa85f64-…`), тож у лог потрапляють дані, яких там бути не має
(THR-09, CWE-532), і рядки неможливо згрупувати за маршрутом для PERF-001/PERF-002.

Маскуємо лише канонічну форму UUID із дефісами: саме її віддає FastAPI для параметрів
типу `uuid.UUID`. Ширше правило помилково маскувало б людиночитані сегменти.
"""

import uuid

PLACEHOLDER = "{id}"


def _is_identifier(segment: str) -> bool:
    """Чи є сегмент UUID у канонічній формі з дефісами."""
    try:
        return str(uuid.UUID(segment)) == segment.lower()
    except ValueError:
        return False


def route_template(path: str) -> str:
    """Повертає шлях, де сегменти-ідентифікатори замінено на `{id}`."""
    return "/".join(PLACEHOLDER if _is_identifier(s) else s for s in path.split("/"))
