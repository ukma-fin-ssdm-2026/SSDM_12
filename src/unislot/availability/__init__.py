"""Модуль `Availability` (HLD §4): ресурси, разові слоти, шаблони, блокування часу.

Записує `resource`, `availability_template`, `slot`, `time_block`. Надає
`AvailabilityService`, `ResourceManagement`, `SlotCatalog`, `HorizonJob` і оголошує
порт `BlockImpactPort`, який реалізує `Booking` (HLD §5.2).

Стан (Лаб 5): поведінку дають заглушки `api.stubs.slot_service` і
`api.stubs.resource_service`; доменний шар — наступний після `Booking`.
"""
