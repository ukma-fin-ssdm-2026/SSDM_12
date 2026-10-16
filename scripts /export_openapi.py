"""Генерує документацію API з коду (Лаб 4): docs/api/openapi-generated.yaml і errors.html.

Запуск з кореня репозиторію (працює однаково на macOS, Linux і Windows):
    python scripts/export_openapi.py           # записати файли
    python scripts/export_openapi.py --check   # перевірка для CI: файли збігаються з кодом

Скрипт лише додає `src/` до шляху імпорту й викликає `api.openapi_export.main`.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from api.openapi_export import main  # імпорт після налаштування sys.path

if __name__ == "__main__":
    sys.exit(main())
