"""Вимір часу відповіді GET-запиту API під паралельним навантаженням (Лаб 4, quality-attributes.md).

Спершу запустіть API (uvicorn api.main:app --app-dir src --port 3000), потім:
    python scripts/api_latency.py --path /api/v1/slots --concurrency 50 --requests 2000

Друкує кількість запитів, частку помилок і перцентилі p50, p95, max у мілісекундах.
Лише стандартна бібліотека — нічого встановлювати не треба.

Обмеження: це методика виміру, а не перевірка PERF-001. На заглушках у пам'яті немає
бази даних, тож число лише показує накладні витрати HTTP і FastAPI. Ціль PERF-001
перевіряється в Лаб 6 на PostgreSQL із 5 000 слотів (TC-060).
"""

import argparse
import statistics
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse


def one_request(url: str, token: str) -> tuple[float, int]:
    # Схему URL перевірено в main(): лише http/https до сервера, який задав користувач.
    headers = {"Authorization": f"Bearer {token}"}
    request = urllib.request.Request(url, headers=headers)  # noqa: S310
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=10) as response:  # nosec B310  # noqa: S310
            response.read()
            status = response.status
    except urllib.error.HTTPError as err:
        status = err.code
    except (urllib.error.URLError, TimeoutError):
        status = 0
    return (time.perf_counter() - started) * 1000, status


def percentile(sorted_values: list[float], share: float) -> float:
    index = max(0, min(len(sorted_values) - 1, round(share * len(sorted_values)) - 1))
    return sorted_values[index]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base-url", default="http://localhost:3000")
    parser.add_argument("--path", default="/api/v1/slots")
    parser.add_argument("--token", default="demo-student")
    parser.add_argument("--concurrency", type=int, default=50)
    parser.add_argument("--requests", type=int, default=2000)
    args = parser.parse_args()

    url = args.base_url.rstrip("/") + args.path
    if urlparse(url).scheme not in {"http", "https"}:
        print("Підтримуються лише адреси http:// і https://")
        return 2

    one_request(url, args.token)  # прогрів: перший запит не враховуємо
    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        results = list(pool.map(lambda _: one_request(url, args.token), range(args.requests)))
    wall = time.perf_counter() - started

    latencies = sorted(ms for ms, _ in results)
    errors = sum(1 for _, status in results if not 200 <= status < 300)
    print(f"URL: {url}")
    print(f"запитів: {len(results)}, паралельно: {args.concurrency}, тривалість: {wall:.1f} с")
    print(f"помилок (не 2xx): {errors} ({errors / len(results):.1%})")
    print(
        f"p50: {statistics.median(latencies):.1f} мс · p95: {percentile(latencies, 0.95):.1f} мс"
        f" · max: {latencies[-1]:.1f} мс"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
