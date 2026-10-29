"""Сховище-заглушка в пам'яті з демо-даними (Лаб 4).

Дані синтетичні (C-003). Час слотів відраховується від моменту запуску, тож
демо працює в будь-який день: «завтра о 10:00 за Києвом», «через 90 хвилин» тощо.
Ідентифікатори сталі (виводяться з назв), щоб на них могли посилатися тести,
приклади в документації та відео.

Справжню цілісність (не більше одного бронювання на слот за конкуренції) гарантує
PostgreSQL (ADR-002). Тут її імітує одне блокування `StubStore.lock`, щоб заглушка
поводилася за контрактом і під паралельними запитами.
"""

from __future__ import annotations

import hashlib
import threading
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from api import clock
from api.enums import BookingStatus, CancellationKind, ResourceType, Role
from api.policy import DEFAULT_BOOKING_LIMIT, DEFAULT_CANCEL_WINDOW, KYIV


def fixture_id(name: str) -> uuid.UUID:
    """Сталий UUID формату v4 для демо-запису: однаковий на всіх машинах (DD-13)."""
    digest = hashlib.sha256(f"unislot-fixture:{name}".encode()).digest()
    return uuid.UUID(bytes=digest[:16], version=4)


class Ids:
    """Ідентифікатори демо-даних. Імена описують, для якої перевірки запис потрібен."""

    STUDENT = fixture_id("user:student")
    STUDENT_2 = fixture_id("user:student-2")
    PROVIDER = fixture_id("user:provider")
    PROVIDER_2 = fixture_id("user:provider-2")
    ADMIN = fixture_id("user:admin")

    RES_DB_CONSULT = fixture_id("resource:db-consultation")
    RES_NET_CONSULT = fixture_id("resource:networks-consultation")
    RES_ROOM_1_225 = fixture_id("resource:room-1-225")
    RES_ROOM_3_317 = fixture_id("resource:room-3-317")

    SLOT_DB_D1_1000 = fixture_id("slot:db:+1:10:00")  # зайнятий іншим студентом
    SLOT_DB_D1_1030 = fixture_id("slot:db:+1:10:30")  # вільний
    SLOT_DB_D1_1100 = fixture_id("slot:db:+1:11:00")  # вільний
    SLOT_DB_D2_1000 = fixture_id("slot:db:+2:10:00")  # бронювання демо-студента
    SLOT_DB_D2_1030 = fixture_id("slot:db:+2:10:30")  # вільний, суміжний з попереднім
    SLOT_NET_D1_1200 = fixture_id("slot:net:+1:12:00")  # вільний
    SLOT_NET_D4_0900 = fixture_id("slot:net:+4:09:00")  # вільний
    SLOT_225_D1_0830 = fixture_id("slot:1-225:+1:08:30")  # вільний
    SLOT_225_D2_1000 = fixture_id(
        "slot:1-225:+2:10:00"
    )  # вільний, перетинається з бронюванням студента
    SLOT_317_D1_1600 = fixture_id("slot:3-317:+1:16:00")  # вільний
    SLOT_317_D3_1600 = fixture_id("slot:3-317:+3:16:00")  # вільний
    SLOT_317_D2_1500 = fixture_id("slot:3-317:+2:15:00")  # у заблокованому проміжку
    SLOT_NET_SOON = fixture_id("slot:net:soon")  # через 90 хв, заброньований студентом
    SLOT_DB_STARTED = fixture_id("slot:db:started")  # почався 10 хв тому
    SLOT_DB_D20 = fixture_id("slot:db:+20:10:00")  # поза горизонтом A-001
    SLOT_DB_PAST = fixture_id("slot:db:-1:10:00")  # минулий

    BLOCK_317_D2 = fixture_id("block:3-317:+2")

    BOOKING_ACTIVE = fixture_id("booking:student:active")  # можна скасувати
    BOOKING_SOON = fixture_id("booking:student:soon")  # граничний час скасування минув
    BOOKING_PAST = fixture_id("booking:student:past")  # завершене
    BOOKING_CANCELLED = fixture_id("booking:student:cancelled")  # скасоване студентом
    BOOKING_OTHER = fixture_id("booking:student-2:active")  # чуже для демо-студента

    POLICY_V1 = fixture_id("policy:v1")


# Демо-токени Лаб 4 (див. api.security). Це не секрети: вони однакові для всіх і
# відкрито описані в документації. Справжні сесії — DD-06, з модулем Auth.
DEMO_TOKENS: dict[str, uuid.UUID] = {
    "demo-student": Ids.STUDENT,
    "demo-student-2": Ids.STUDENT_2,
    "demo-provider": Ids.PROVIDER,
    "demo-provider-2": Ids.PROVIDER_2,
    "demo-admin": Ids.ADMIN,
}


@dataclass
class UserRec:
    """Користувач (`app_user` + ролі з `user_role`)."""

    id: uuid.UUID
    full_name: str
    email: str
    roles: frozenset[Role]


@dataclass
class ResourceRec:
    """Ресурс: консультація або аудиторія з провайдером (INV-08, INV-15)."""

    id: uuid.UUID
    name: str
    type: ResourceType
    capacity: int | None
    provider_id: uuid.UUID


@dataclass
class SlotRec:
    """Слот ресурсу; час зберігається в UTC (A-007)."""

    id: uuid.UUID
    resource_id: uuid.UUID
    starts_at: datetime
    ends_at: datetime


@dataclass
class TimeBlockRec:
    """Проміжок, який провайдер оголосив недоступним (FR-014)."""

    id: uuid.UUID
    resource_id: uuid.UUID
    starts_at: datetime
    ends_at: datetime
    reason: str


@dataclass
class PolicyRec:
    """Політика бронювання: ліміт A-002 і вікно скасування A-003."""

    id: uuid.UUID
    booking_limit: int  # A-002
    cancel_window: timedelta  # A-003


@dataclass
class BookingRec:
    """Бронювання; у сховищі лише `confirmed` або `cancelled` (`data-model.md` §7)."""

    id: uuid.UUID
    slot_id: uuid.UUID
    student_id: uuid.UUID
    status: BookingStatus
    policy_id: uuid.UUID
    cancel_deadline_at: datetime  # FR-041: фіксується під час створення
    created_at: datetime
    cancelled_at: datetime | None = None
    cancelled_by: uuid.UUID | None = None
    cancellation_kind: CancellationKind | None = None
    cancellation_reason: str | None = None
    rescheduled_to_id: uuid.UUID | None = None


@dataclass
class StubStore:
    """Усі демо-дані процесу. `lock` серіалізує зміни, як транзакція в БД."""

    lock: threading.RLock = field(default_factory=threading.RLock)
    users: dict[uuid.UUID, UserRec] = field(default_factory=dict)
    resources: dict[uuid.UUID, ResourceRec] = field(default_factory=dict)
    slots: dict[uuid.UUID, SlotRec] = field(default_factory=dict)
    blocks: dict[uuid.UUID, TimeBlockRec] = field(default_factory=dict)
    bookings: dict[uuid.UUID, BookingRec] = field(default_factory=dict)
    reminders: dict[uuid.UUID, datetime] = field(default_factory=dict)  # FR-051, моменти в UTC
    policy: PolicyRec | None = None
    audit: list[dict[str, Any]] = field(default_factory=list)  # FR-066, лише для заглушки
    idempotency: dict[tuple[uuid.UUID, str], dict[str, Any]] = field(default_factory=dict)

    # --- Наповнення ------------------------------------------------------------------

    def reset(self, now: datetime | None = None) -> None:
        """Відновлює демо-дані відносно моменту `now` (за замовчуванням — зараз)."""
        now = (now or clock.utc_now()).replace(second=0, microsecond=0)
        today = now.astimezone(KYIV).date()
        with self.lock:
            self.users.clear()
            self.resources.clear()
            self.slots.clear()
            self.blocks.clear()
            self.bookings.clear()
            self.reminders.clear()
            self.audit.clear()
            self.idempotency.clear()
            self._fill_users()
            self._fill_resources()
            self._fill_slots(now, today)
            self.policy = PolicyRec(Ids.POLICY_V1, DEFAULT_BOOKING_LIMIT, DEFAULT_CANCEL_WINDOW)
            self._fill_bookings(now, self.policy)

    def _fill_users(self) -> None:
        for uid, name, email, roles in (
            (Ids.STUDENT, "Олена Коваль", "olena.koval@unislot.example", {Role.STUDENT}),
            (Ids.STUDENT_2, "Андрій Мельник", "andrii.melnyk@unislot.example", {Role.STUDENT}),
            (Ids.PROVIDER, "Ірина Шевченко", "iryna.shevchenko@unislot.example", {Role.PROVIDER}),
            (Ids.PROVIDER_2, "Олег Бондар", "oleh.bondar@unislot.example", {Role.PROVIDER}),
            (Ids.ADMIN, "Марія Ткаченко", "mariia.tkachenko@unislot.example", {Role.ADMIN}),
        ):
            self.users[uid] = UserRec(uid, name, email, frozenset(roles))

    def _fill_resources(self) -> None:
        for rec in (
            ResourceRec(
                Ids.RES_DB_CONSULT,
                "Консультація з баз даних",
                ResourceType.CONSULTATION,
                None,
                Ids.PROVIDER,
            ),
            ResourceRec(
                Ids.RES_NET_CONSULT,
                "Консультація з комп'ютерних мереж",
                ResourceType.CONSULTATION,
                None,
                Ids.PROVIDER_2,
            ),
            ResourceRec(
                Ids.RES_ROOM_1_225, "Аудиторія 1-225", ResourceType.ROOM, 30, Ids.PROVIDER_2
            ),
            ResourceRec(Ids.RES_ROOM_3_317, "Аудиторія 3-317", ResourceType.ROOM, 12, Ids.PROVIDER),
        ):
            self.resources[rec.id] = rec

    def _fill_slots(self, now: datetime, today: date) -> None:
        def kyiv(day: int, hh: int, mm: int) -> datetime:
            local = datetime.combine(today + timedelta(days=day), time(hh, mm), tzinfo=KYIV)
            return local.astimezone(UTC)

        plan = [
            (Ids.SLOT_DB_D1_1000, Ids.RES_DB_CONSULT, kyiv(1, 10, 0), 30),
            (Ids.SLOT_DB_D1_1030, Ids.RES_DB_CONSULT, kyiv(1, 10, 30), 30),
            (Ids.SLOT_DB_D1_1100, Ids.RES_DB_CONSULT, kyiv(1, 11, 0), 30),
            (Ids.SLOT_DB_D2_1000, Ids.RES_DB_CONSULT, kyiv(2, 10, 0), 30),
            (Ids.SLOT_DB_D2_1030, Ids.RES_DB_CONSULT, kyiv(2, 10, 30), 30),
            (Ids.SLOT_NET_D1_1200, Ids.RES_NET_CONSULT, kyiv(1, 12, 0), 45),
            (Ids.SLOT_NET_D4_0900, Ids.RES_NET_CONSULT, kyiv(4, 9, 0), 45),
            (Ids.SLOT_225_D1_0830, Ids.RES_ROOM_1_225, kyiv(1, 8, 30), 90),
            (Ids.SLOT_225_D2_1000, Ids.RES_ROOM_1_225, kyiv(2, 10, 0), 90),
            (Ids.SLOT_317_D1_1600, Ids.RES_ROOM_3_317, kyiv(1, 16, 0), 60),
            (Ids.SLOT_317_D3_1600, Ids.RES_ROOM_3_317, kyiv(3, 16, 0), 60),
            (Ids.SLOT_317_D2_1500, Ids.RES_ROOM_3_317, kyiv(2, 15, 0), 60),
            (Ids.SLOT_NET_SOON, Ids.RES_NET_CONSULT, now + timedelta(minutes=90), 30),
            (Ids.SLOT_DB_STARTED, Ids.RES_DB_CONSULT, now - timedelta(minutes=10), 30),
            (Ids.SLOT_DB_D20, Ids.RES_DB_CONSULT, kyiv(20, 10, 0), 30),
            (Ids.SLOT_DB_PAST, Ids.RES_DB_CONSULT, kyiv(-1, 10, 0), 30),
        ]
        for sid, rid, start, minutes in plan:
            self.slots[sid] = SlotRec(sid, rid, start, start + timedelta(minutes=minutes))
        self.blocks[Ids.BLOCK_317_D2] = TimeBlockRec(
            Ids.BLOCK_317_D2,
            Ids.RES_ROOM_3_317,
            kyiv(2, 14, 30),
            kyiv(2, 16, 30),
            "Засідання кафедри",
        )

    def _fill_bookings(self, now: datetime, policy: PolicyRec) -> None:
        def book(bid: uuid.UUID, sid: uuid.UUID, student: uuid.UUID) -> BookingRec:
            slot = self.slots[sid]
            rec = BookingRec(
                id=bid,
                slot_id=sid,
                student_id=student,
                status=BookingStatus.CONFIRMED,
                policy_id=policy.id,
                cancel_deadline_at=slot.starts_at - policy.cancel_window,
                created_at=min(now, slot.starts_at) - timedelta(days=1),
            )
            self.bookings[bid] = rec
            return rec

        book(Ids.BOOKING_ACTIVE, Ids.SLOT_DB_D2_1000, Ids.STUDENT)
        book(Ids.BOOKING_SOON, Ids.SLOT_NET_SOON, Ids.STUDENT)
        book(Ids.BOOKING_PAST, Ids.SLOT_DB_PAST, Ids.STUDENT)
        book(Ids.BOOKING_OTHER, Ids.SLOT_DB_D1_1000, Ids.STUDENT_2)
        cancelled = book(Ids.BOOKING_CANCELLED, Ids.SLOT_225_D2_1000, Ids.STUDENT)
        cancelled.status = BookingStatus.CANCELLED
        cancelled.cancelled_at = now - timedelta(hours=3)
        cancelled.cancelled_by = Ids.STUDENT
        cancelled.cancellation_kind = CancellationKind.STUDENT

    # --- Запити, спільні для модулів --------------------------------------------------

    def user_by_token(self, token: str) -> UserRec | None:
        """Користувач за демо-токеном або None, якщо токен невідомий (DD-18)."""
        user_id = DEMO_TOKENS.get(token)
        return self.users.get(user_id) if user_id else None

    def confirmed_booking_for_slot(self, slot_id: uuid.UUID) -> BookingRec | None:
        """Чинне (`confirmed`) бронювання слота, якщо є (INV-01: не більше одного)."""
        return next(
            (
                b
                for b in self.bookings.values()
                if b.slot_id == slot_id and b.status is BookingStatus.CONFIRMED
            ),
            None,
        )

    def is_blocked(self, slot: SlotRec) -> bool:
        """Чи перетинає слот блокування провайдера на тому самому ресурсі (FR-014)."""
        return any(
            b.resource_id == slot.resource_id
            and b.starts_at < slot.ends_at
            and slot.starts_at < b.ends_at
            for b in self.blocks.values()
        )


store = StubStore()
store.reset()
