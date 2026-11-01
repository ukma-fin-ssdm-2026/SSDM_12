"""Розгортання тижневого розкладу в абсолютні інтервали (FR-012, A-007)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class WeeklyPattern:
    """Щотижневий проміжок одного дня в локальному часі; weekday — ISO 1…7."""

    weekday: int
    start_local: time
    end_local: time
    slot_minutes: int
    valid_from: date
    valid_to: date | None = None

    def __post_init__(self) -> None:
        """Не допускає порожніх інтервалів, часткових слотів чи часу з поясом."""
        if type(self.weekday) is not int or not 1 <= self.weekday <= 7:
            raise ValueError("weekday має бути цілим числом від 1 до 7")
        if type(self.slot_minutes) is not int or self.slot_minutes <= 0:
            raise ValueError("slot_minutes має бути додатним цілим числом")
        for local in (self.start_local, self.end_local):
            if local.tzinfo is not None or local.second or local.microsecond:
                raise ValueError("локальний час задається без поясу з точністю до хвилини")
        length = (
            self.end_local.hour * 60
            + self.end_local.minute
            - self.start_local.hour * 60
            - self.start_local.minute
        )
        if length <= 0 or length % self.slot_minutes:
            raise ValueError("проміжок має складатися з цілих слотів у межах одного дня")
        if self.valid_to is not None and self.valid_to < self.valid_from:
            raise ValueError("valid_to має бути не раніше valid_from")


@dataclass(frozen=True)
class Occurrence:
    """Кандидат у слот; обидва моменти в UTC."""

    starts_at: datetime
    ends_at: datetime


@dataclass(frozen=True)
class CalendarConflict:
    """Локальний час, який потребує рішення провайдера через перехід годинника."""

    day: date
    start_local: time
    code: str


def _utc_choices(local: datetime, zone: ZoneInfo) -> set[datetime]:
    # Round-trip відрізняє неіснуючий час від обох варіантів неоднозначного часу.
    result = set()
    for fold in (0, 1):
        utc = local.replace(tzinfo=zone, fold=fold).astimezone(UTC)
        if utc.astimezone(zone).replace(tzinfo=None) == local:
            result.add(utc)
    return result


def generate_occurrences(
    pattern: WeeklyPattern,
    now: datetime,
    horizon: timedelta,
    zone: ZoneInfo,
) -> tuple[list[Occurrence], list[CalendarConflict]]:
    """Створює слоти на (now, now+horizon], зберігаючи локальний час тижня.

    Не вгадує fold і не пересуває час у весняному розриві: такий кандидат потрапляє
    в перелік конфліктів. Тривалість слота — абсолютні хвилини, як для разового слота.
    """
    if now.utcoffset() is None or horizon <= timedelta(0):
        raise ValueError("потрібні now із часовим поясом та додатний горизонт")
    now = now.astimezone(UTC)
    until = now + horizon
    first = max(pattern.valid_from, now.astimezone(zone).date())
    last = until.astimezone(zone).date()
    if pattern.valid_to is not None:
        last = min(last, pattern.valid_to)
    step = timedelta(minutes=pattern.slot_minutes)
    slots, conflicts = [], []
    local_now = now.astimezone(zone).replace(tzinfo=None)
    local_until = until.astimezone(zone).replace(tzinfo=None)
    for offset in range((last - first).days + 1):
        day = first + timedelta(days=offset)
        if day.isoweekday() != pattern.weekday:
            continue
        cursor = datetime.combine(day, pattern.start_local)
        end = datetime.combine(day, pattern.end_local)
        while cursor < end:
            following = cursor + step
            starts, ends = _utc_choices(cursor, zone), _utc_choices(following, zone)
            if len(starts) != 1 or len(ends) != 1:
                code = (
                    "nonexistent_local_time" if not starts or not ends else "ambiguous_local_time"
                )
                in_horizon = (
                    any(now < start <= until for start in starts)
                    if starts
                    else local_now < cursor <= local_until
                )
                if in_horizon:
                    conflicts.append(CalendarConflict(day, cursor.time(), code))
            else:
                start_utc, end_utc = next(iter(starts)), next(iter(ends))
                if now < start_utc <= until:
                    if end_utc - start_utc == step:
                        slots.append(Occurrence(start_utc, end_utc))
                    else:
                        conflicts.append(CalendarConflict(day, cursor.time(), "dst_duration"))
            cursor = following
    return slots, conflicts
