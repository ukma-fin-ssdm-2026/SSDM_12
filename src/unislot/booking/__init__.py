"""Модуль `Booking` (HLD §4): бронювання, скасування, перенесення, власні бронювання.

Записує `booking` і тримає інваріанти бронювання (ADR-002). Надає `BookingService`;
використовує `SlotCatalog`, `PolicyProvider`, `NotificationOutbox`; реалізує порт
`BlockImpactPort` модуля `Availability` (HLD §5.2).

Стан (Лаб 5): доменний шар `domain` — стани, правила й доменні помилки бронювання.
Шар application поки виконує заглушка `api.stubs.booking_service`; `infrastructure`
з'явиться разом із PostgreSQL (ADR-002).
"""
