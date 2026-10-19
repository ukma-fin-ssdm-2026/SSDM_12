"""MCP-сервер, згенерований з REST API UniSlot (бонус Лаб 4).

Кожна кінцева точка стає інструментом MCP: назва — operationId (`search_free_slots`,
`create_booking`…), опис і схема параметрів — з тих самих анотацій, що й Swagger UI.
FastMCP викликає застосунок FastAPI напряму, тож окремо запускати сервер API не треба.

Запуск з кореня репозиторію (окреме середовище з `requirements-mcp.txt`):

    python src/api/mcp_server.py

Агент діє від імені одного демо-користувача: токен задає змінна `UNISLOT_MCP_TOKEN`
(за замовчуванням `demo-student`). Протокол — stdio, тож у stdout нічого не друкуємо:
журнали застосунку йдуть у stderr.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Запуск як скрипта: корінь імпорту пакета `api` — каталог src/.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
# Агент не має перезаписувати docs/api/ під час старту.
os.environ.setdefault("UNISLOT_EXPORT_OPENAPI", "0")

from fastmcp import FastMCP

from api.main import app

TOKEN = os.environ.get("UNISLOT_MCP_TOKEN", "demo-student")

mcp = FastMCP.from_fastapi(
    app=app,
    name="UniSlot",
    httpx_client_kwargs={"headers": {"Authorization": f"Bearer {TOKEN}"}},
)

if __name__ == "__main__":
    mcp.run()  # транспорт stdio
