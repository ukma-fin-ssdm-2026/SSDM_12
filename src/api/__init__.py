"""REST API UniSlot — компонент `REST API` з HLD §4 (Лаб 4, підхід Code-First).

Специфікація OpenAPI не пишеться вручну: її генерує FastAPI з цього пакета
(роутери, схеми Pydantic, докстрінги). Згенерований файл —
`docs/api/openapi-generated.yaml`; як його отримати — `api.openapi_export`.

Бізнес-логіки модулів `Booking`, `Availability`, `Search` тут ще немає: роутери
звертаються до заглушок у `api.stubs`, які в Лаб 5–6 замінить справжній шар
application модулів (HLD §6, DD-17).
"""
