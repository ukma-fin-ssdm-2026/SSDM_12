"""Модуль `Booking` (HLD §4): бронювання, скасування, перенесення, власні бронювання.

Записує `booking` і тримає інваріанти бронювання (ADR-002). Надає `BookingService`;
використовує `SlotCatalog`, `PolicyProvider`, `NotificationOutbox`; реалізує порт
`BlockImpactPort` модуля `Availability` (HLD §5.2).

Стан (Лаб 5): правила бронювання поки в заглушці `api.stubs.booking_service`;
перший доменний шар проєкту з'являється саме тут.
"""
