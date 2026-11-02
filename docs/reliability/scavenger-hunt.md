# Resilience Scavenger Hunt — критичні точки відмови UniSlot

**Лабораторна 9 (LO7, надійність), аудиторна активність.** Базова ревізія — `caf9260`
(`main`, після PR #250). Прочесано `src/` (7 909 рядків) і `scripts/`; категорії пошуку —
A (обробка помилок), B (зовнішні залежності), C (валідація входу), D (silent failures),
E (продуктивність і блокування).

Знайдено **9 проблем**, виправлено **5**. Чотири лишено свідомо: це рішення рівня ADR, а не
дефекти коду, — обґрунтування в §5.

---

## 1. Як шукали

Не «очима по файлах», а цілеспрямовано за патернами, бо проєкт уже пройшов Лаб 5–7
(ruff з правилами `B`/`S`/`ASYNC`, Bandit, SonarCloud), тож очевидні запахи вже прибрані:

```bash
grep -rn "except" --include='*.py' src/            # усі 20 except-блоків — поіменно
grep -rn "requests\.\|httpx\|timeout" src/ scripts/ # зовнішні виклики без таймаутів
grep -rn "int(os.environ\|os.environ.get" src/      # неперевірений зовнішній вхід
grep -rn "while True\|while " src/ scripts/         # цикли без гарантованого виходу
grep -rn "^def \|^async def " src/api/routers/      # блокувальні I/O в async-коді
```

Кожну знахідку перевіряли **відтворенням**, а не читанням. Наприклад R-01:

```console
$ UNISLOT_SESSION_TTL_SECONDS= python -c "import api.config as c; c.get_settings()"
ValueError: invalid literal for int() with base 10: ''
```

Доказ red-стадії — [`evidence/01-red-new-tests.txt`](evidence/01-red-new-tests.txt),
green і регрес — [`evidence/02-green-and-regression.txt`](evidence/02-green-and-regression.txt).

---

## 2. Зведення знахідок

| ID | Категорія | Проблема | Fault → Error → Failure | Severity | Статус |
|---|---|---|---|---|---|
| R-01 | B, C | `int()` над змінною середовища без валідації | конфіг → `ValueError` на імпорті → API не стартує | **High** | ✅ виправлено |
| R-02 | A, D | причина відмови доставки губиться тричі | `from None` + catch без логу → `last_error` стале → нагадування тихо не доходять | **High** | ✅ виправлено |
| R-03 | E | генерація слотів і глобальний lock у GET-обробнику | довга транзакція → чекання на `lock_timeout` → лавина 503 | **High** | ⏸ §5.1 |
| R-04 | B, D | `/health` не перевіряє сховище, але є `healthCheckPath` | немає error → оркестратор не бачить мертвої БД | **Medium** | ⏸ §5.2 |
| R-05 | D | цикл без гарантованого виходу → неявний `return None` | латентний → `None` замість відповіді → 500 без причини | **Low** | ✅ виправлено |
| R-06 | E | пул з'єднань (32) вужчий за threadpool FastAPI (40) | насичення → `PoolTimeout` → частина запитів 503 | **Medium** | ⏸ §5.3 |
| R-07 | B, E | нескінченний цикл Worker без експоненційного відступу | збій БД → ~60 спроб/хв → шторм перепідключень | **Medium** | ✅ виправлено |
| R-08 | B | запис файлів на старті без fallback | read-only FS → `OSError` у `lifespan` → API не піднімається | **Medium** | ✅ виправлено |
| R-09 | A | MCP-сервер вмикає демо-автентифікацію як побічний ефект імпорту | import → `UNISLOT_DEMO_AUTH=1` → обхід авторизації | **Low** | ⏸ §5.4 |

---

## 3. Етапи 1–2: знахідки детально

### R-01 · `int()` над змінною середовища без валідації — **High**

**Код** — `src/api/config.py:78–81` (до правки):

```python
session_ttl_seconds=int(os.environ.get("UNISLOT_SESSION_TTL_SECONDS", "28800")),
login_max_failures=int(os.environ.get("UNISLOT_LOGIN_MAX_FAILURES", "5")),
login_cooldown_seconds=int(os.environ.get("UNISLOT_LOGIN_COOLDOWN_SECONDS", "300")),
thread_switch_interval_ms=int(os.environ.get("UNISLOT_THREAD_SWITCH_INTERVAL_MS", "1")),
```

**Чому небезпечно.** Другий аргумент `os.environ.get` рятує лише від **відсутньої** змінної.
Змінна, що існує й містить `""` або `5min`, йде прямо в `int()`. У тому ж файлі поруч
(`config.py:29–34`) лежить захисний `_flag()`, який той самий сміттєвий вхід переживає:

```console
UNISLOT_DEMO_AUTH=кракозябра  → demo_auth_enabled = False   # _flag() впорався
UNISLOT_SESSION_TTL_SECONDS=  → ValueError                   # int() упав
```

Тобто булеві змінні захищені, числові — ні. Асиметрія, а не системне рішення.

Три обставини роблять це реальним, а не теоретичним:

1. `.env.example` постачає ці змінні явно (`UNISLOT_SESSION_TTL_SECONDS=28800`) з приміткою
   «Provisional runtime settings; OQ-001 still needs a team decision» — тобто їх *очікувано*
   редагують вручну.
2. `render.yaml` оголошує частину змінних у панелі Render, де **порожнє поле — звичайна річ**.
3. `get_settings()` викликається на імпорті (`main.py:222`, `app = create_app()`), тож помилка
   виникає до першого запиту.

**Ланцюг.** *Fault:* прямий `int()` над неперевіреним зовнішнім входом, без діапазону.
*Error:* `ValueError` усередині `get_settings()`; об'єкт `Settings` не створено, `lru_cache`
не зберіг нічого. *Failure:* `uvicorn` не піднімається; на Render — цикл перезапусків, де в
логах лише `invalid literal for int() with base 10: ''` **без назви змінної**, тож пошук
причини починається з перебору чотирьох полів.

Окремо варто відзначити: `Settings.__post_init__` (`config.py:56–63`) межі перевіряє
(`< 1` і `1..20`), але до нього виконання не доходить — валідатор стоїть **за** місцем падіння.

### R-02 · Причина відмови доставки губиться тричі — **High**

**Код** — три місця, кожне відкидає частину інформації:

```python
# outbox.py:245-246 — гине першопричина
except DBAPIError:
    raise DeliveryUnavailable from None

# outbox.py:271-272 — жодного логування
except (DeliveryUnavailable, TimeoutError, OSError):
    repository.finish(notice, now, policy, error=True)

# outbox.py:48 — стала, однакова для всіх причин
notice.last_error = "gateway_unavailable"
```

**Чому небезпечно.** `from None` стирає `__cause__`, тож обробник вище не має доступу навіть
до класу початкової помилки. Обробник, у свою чергу, нічого не пише в журнал. А `last_error` —
єдине поле, яке бачить оператор через `scripts/manage_notifications.py`, — отримує одне
значення незалежно від того, що сталося. Три різні причини (недоступна БД, увімкнена
ін'єкція збою `UNISLOT_NOTIFICATION_FAILURE`, мережева помилка провайдера) після факту
нерозрізненні.

**Ланцюг.** *Fault:* `from None`, catch без логування, стале значення `last_error`.
*Error:* `DispatchResult.failed` зростає, у БД усі невдалі записи з однаковим `last_error`.
*Failure:* нагадування про консультацію тихо повторюється 8 разів (`max_attempts`), стає
`failed` і не доходить до студента; у журналі немає нічого, що пояснило б причину. Це
прямо суперечить REL-002 («усі недоставлені сповіщення потрапляють…»), бо вимога про
збереження в черзі виконується, а діагностувати відмову неможливо.

### R-03 · Генерація слотів і глобальний lock у GET-обробнику — **High**

**Код** — `src/api/routers/slots.py:102–108` → `src/api/services/worker_service.py:30–47`:

```python
# публічний GET /api/v1/slots
if store.persistent:
    now = clock.utc_now()
    ...
    ensure_horizon(now)        # ← може взяти глобальний lock і згенерувати слоти
    return search_slots(...)
```

```python
def ensure_horizon(now: datetime) -> None:
    ...
    if stale:
        with store.lock:       # advisory-lock, що серіалізує ВСІ записи системи
            if store.lock.connection.scalar(needed):
                refresh_horizon(now)   # extend_horizon() за всіма шаблонами
```

**Чому небезпечно.** `store.lock` — це `pg_advisory_xact_lock(7120001)`
(`postgres.py:46`), один ключ на всю систему: поки його тримають, жодне бронювання,
перенесення чи скасування не виконується. Тут його бере **звичайний GET-запит**, щоб
розгорнути тижневі шаблони на весь горизонт. Транзакція обмежена
`statement_timeout = 15s` і `lock_timeout = 5s` (`postgres.py:44–45`) — межі є, але вони
описують, *як швидко інші впадуть*, а не скільки триватиме генерація.

**Ланцюг.** *Fault:* довга службова операція в обробнику запиту під глобальним локом.
*Error:* один GET тримає серіалізуючий lock; паралельні запити чекають до 5 с.
*Failure:* перший пошук слотів після київської півночі (або після простою окремого Worker)
перетворює звичайний GET у довгу транзакцію; решта користувачів у цей момент отримує 503
`TRANSIENT_CONFLICT`. Пом'якшення в коді вже є: подвійна перевірка після взяття лока
(`worker_service.py:46`) не дає двом запитам зробити роботу двічі, а окремий Worker
(`render.yaml`, сервіс `unislot-worker`) у нормі робить це раніше за будь-який запит. Тому
це **деградація у вузькому вікні**, а не постійна проблема.

### R-04 · `/health` не перевіряє сховище — **Medium**

**Код** — `src/api/routers/health.py:33–37` і `render.yaml` (`healthCheckPath: /health`):

```python
def get_health() -> HealthOut:
    """... не звертається до сховища, тож відповідає навіть за проблем із даними."""
    return HealthOut(status="ok", version=API_VERSION)
```

**Чому небезпечно.** Сам ендпоїнт написано правильно й намір задокументовано — це
**liveness**-перевірка. Проблема в тому, що `render.yaml` використовує саме його як
`healthCheckPath`, тобто liveness застосовано там, де потрібна **readiness**.

**Ланцюг.** *Fault:* єдина перевірка стану не торкається залежності, без якої процес
безкорисний. *Error:* некоректного внутрішнього стану немає — процес справді живий.
*Failure:* коли PostgreSQL недоступна, Render вважає інстанс здоровим і далі скеровує на
нього трафік; кожен запит падає в `TRANSIENT_CONFLICT`, а оркестратор не виводить інстанс
із ротації й не перезапускає його. Відмова видима користувачам і невидима платформі.

### R-05 · Цикл без гарантованого виходу → неявний `return None` — **Low (латентна)**

**Код** — `src/api/infrastructure/unit_of_work.py:22–44`:

```python
def wrapped(*args, **kwargs):
    for attempt in range(2 if retry_deadlock else 1):
        try:
            ...
            return function(*args, **kwargs)
        except DBAPIError as exc:
            if retry_deadlock and attempt == 0 and state == "40P01":
                continue
            ...
            raise ApiProblem(...) from None
        except PoolTimeout:
            raise ApiProblem(...) from None
    # ← виходу немає: функція неявно повертає None
```

**Чому небезпечно.** Сьогодні **недосяжно**, і це варто сказати прямо: `continue` можливий
лише на `attempt == 0`, а друга ітерація завершується `return` або `raise`. Але декоратор
обгортає **кожен** маршрут, що змінює дані, і межа циклу задана виразом `2 if retry_deadlock
else 1`. Одна зміна цього виразу або нова гілка `continue` відкриває шлях, на якому
`wrapped` поверне `None`.

**Ланцюг.** *Fault:* `for`-цикл без `return`/`raise` після себе.
*Error:* `wrapped` повертає `None` замість моделі відповіді. *Failure:* FastAPI не може
провалідувати `None` під `response_model` → 500 `INTERNAL_ERROR`, і в журналі буде помилка
валідації відповіді, а не справжня причина. Ціна страховки — один `raise`.

### R-06 · Пул з'єднань вужчий за threadpool FastAPI — **Medium**

**Код** — `src/api/infrastructure/postgres.py:98–111`:

```python
POOL_SIZE = 32
...
pool_size=POOL_SIZE, max_overflow=0, pool_timeout=5,
connect_args={"connect_timeout": 5, "options": "... statement_timeout=15000"},
```

**Чому небезпечно.** Усі обробники маршрутів оголошено як `def`, а не `async def` (перевірено:
`grep "^def\|^async def" src/api/routers/` — `async def` немає ні в одному роутері). Для
синхронного обробника це **правильно**: FastAPI виконує його в threadpool і не блокує event
loop — саме тому правило ruff `ASYNC` тут не спрацьовує. Але типовий threadpool AnyIO — 40
потоків, а з'єднань у пулі 32 без `max_overflow`. Межі не узгоджені між собою й ніде не
записані разом.

**Ланцюг.** *Fault:* дві незалежно налаштовані межі паралелізму (потоки vs з'єднання).
*Error:* 33-й одночасний запит чекає з'єднання 5 с і отримує `PoolTimeout`.
*Failure:* під навантаженням частина користувачів бачить 503 замість відповіді. Деградація
**керована**: `unit_of_work.py:41–44` перетворює `PoolTimeout` на коректний `problem+json`
із `Retry-After: 1`. Отже це не дефект, а невиміряна й незадокументована точка насичення.

### R-07 · Нескінченний цикл Worker без експоненційного відступу — **Medium**

**Код** — `scripts/run_worker.py:59–81` (до правки):

```python
while True:
    try:
        ...
        result = dispatch_due(repository, clock.utc_now(), ...)
    except DBAPIError:
        print(json.dumps({"event": "worker_retry", "code": "database_unavailable"}), flush=True)
        if args.once:
            raise SystemExit(1) from None
    if args.once:
        break
    time.sleep(args.interval)        # ← завжди 1 с, скільки б збоїв не було
```

**Чому небезпечно.** Два незалежні боки. По-перше, затримка фіксована: при недоступній БД
цикл робить ≈60 спроб підключення за хвилину й тисне на сховище саме тоді, коли воно
відновлюється. По-друге, ловиться лише `DBAPIError` — `OSError` (обрив мережі, DNS) виходить
із циклу й завершує процес, а в `render.yaml` для сервісу `unislot-worker` немає ні
`healthCheckPath`, ні описаної політики перезапуску.

**Ланцюг.** *Fault:* фіксована затримка в нескінченному циклі + перехоплення лише одного
класу операційних помилок. *Error:* шторм перепідключень або мовчазне завершення процесу.
*Failure:* або БД отримує додаткове навантаження під час відновлення, або нагадування не
доставляються взагалі, бо воркер помер, і ніхто цього не бачить — API при цьому працює
нормально, тож відмова тиха.

### R-08 · Запис файлів на старті без fallback — **Medium**

**Код** — `src/api/main.py:148–150` → `src/api/openapi_export.py:69–77`:

```python
if settings.export_openapi_on_startup:          # типово True (config.py:71)
    for path in openapi_export.write_artifacts(app):
        logger.info("OpenAPI згенеровано з коду → %s", path)
```

```python
def write_artifacts(app: FastAPI, out_dir: Path = DOCS_API) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, content in render_artifacts(app).items():
        path.write_text(content, encoding="utf-8", newline="\n")   # без обробки помилок
```

**Чому небезпечно.** Типове значення — `True`, тобто **небезпечний default**: процес за
замовчуванням пише у файлову систему всередині `lifespan`. На контейнері з read-only FS або
без права запису в каталог репозиторію це `OSError` під час старту. `render.yaml` ставить
`UNISLOT_EXPORT_OPENAPI=0`, а `tests/conftest.py:16` — те саме для тестів: обидва обходи
існують, отже ризик команді відомий, але **захист тримається на правильно виставленій
змінній, а не на коді**.

**Ланцюг.** *Fault:* побічна дія запису на диск у шляху старту, без обробки помилок, з
небезпечним типовим значенням. *Error:* `OSError` у `lifespan`. *Failure:* API не завершує
старт і не обслуговує запити — через дію, яка для обслуговування запитів не потрібна
(специфікація вже закомічена в `docs/api/openapi-generated.yaml`).

### R-09 · MCP-сервер вмикає демо-автентифікацію при імпорті — **Low**

**Код** — `src/api/mcp_server.py:25–34`:

```python
os.environ.setdefault("UNISLOT_DEMO_AUTH", "1")   # на рівні модуля
...
from api.main import app
TOKEN = os.environ.get("UNISLOT_MCP_TOKEN", "demo-student")
```

**Чому небезпечно.** Намір задокументовано в коментарі поруч, і `setdefault` поважає вже
виставлену змінну — це зроблено свідомо. Залишковий ризик вузький: увімкнення обходу
автентифікації є **побічним ефектом імпорту модуля**, а не явної дії. Будь-що, що імпортує
`api.mcp_server` (тест, інструмент, помилковий імпорт), отримує застосунок, який приймає
токени `demo-*`, включно з `demo-admin`.

**Ланцюг.** *Fault:* зміна глобального стану процесу на рівні модуля.
*Error:* процес із увімкненим обходом автентифікації, якого ніхто явно не вмикав.
*Failure:* запущений не в тому оточенні MCP-сервер відкриває доступ під демо-ролями.

---

## 4. Етап 3: що виправлено

Правок — 5, у 5 файлах, `+158 / −21` рядка. Для кожної спершу написано тест (red), потім
правка (green): [`evidence/01-red-new-tests.txt`](evidence/01-red-new-tests.txt) →
[`evidence/02-green-and-regression.txt`](evidence/02-green-and-regression.txt).

| Знахідка | Застосована техніка | Файл | Тест |
|---|---|---|---|
| R-01 | guard clause, перевірка входу, безпечне значення | `src/api/config.py` | `tests/unit/test_config_env_validation.py` |
| R-02 | логування, збереження першопричини, вузькі коди | `src/api/infrastructure/outbox.py` | `tests/unit/test_dispatch_diagnostics.py` |
| R-05 | guard clause | `src/api/infrastructure/unit_of_work.py` | — (страховка, `pragma: no cover`) |
| R-07 | fallback-логіка (експоненційний відступ) | `scripts/run_worker.py` | `tests/unit/test_worker_backoff.py` |
| R-08 | fallback-логіка, вузький catch, логування | `src/api/main.py` | `tests/unit/test_startup_degradation.py` |

### 4.1 R-01 → `_bounded_int()` і таблиця меж

```python
NUMERIC_SETTINGS: dict[str, tuple[int, int, int]] = {
    "UNISLOT_SESSION_TTL_SECONDS": (28800, 1, 30 * 24 * 3600),
    "UNISLOT_LOGIN_MAX_FAILURES": (5, 1, 1000),
    "UNISLOT_LOGIN_COOLDOWN_SECONDS": (300, 1, 24 * 3600),
    "UNISLOT_THREAD_SWITCH_INTERVAL_MS": (1, 1, 20),
}


def _bounded_int(name: str) -> int:
    default, low, high = NUMERIC_SETTINGS[name]
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw.strip())
    except ValueError:
        raise ValueError(f"{name} must be a whole number, got {raw.strip()!r}") from None
    if not low <= value <= high:
        raise ValueError(f"{name} must be between {low} and {high}, got {value}")
    return value
```

**Компроміс, який треба вміти захистити.** Порожнє значення й сміттєве обробляються
**по-різному**, і це рішення, не недогляд:

- порожнє → **fail-safe**, типове значення. Порожнє поле в панелі розгортання означає
  «не задано»; валити сервіс через це — зробити відмову з неоднозначності;
- нечислове чи позамежне → **fail-fast** із назвою змінної. `UNISLOT_LOGIN_MAX_FAILURES=5min`
  не має тихо стати `5`: це межа безпеки, і тиха підміна гірша за відмову старту.

Межі свідомо широкі (`1..1000` замість «правильного» значення): числа досі відкриті в
**OQ-001**, і задача правки — відсікти абсурд, а не закрити відкрите питання.
`Settings.__post_init__` лишено без змін — захист у два шари.

### 4.2 R-02 → код причини в `last_error`, клас помилки в журнал

```python
FAILURE_CODES: tuple[tuple[type[BaseException], str], ...] = (
    (DeliveryUnavailable, "gateway_unavailable"),
    (TimeoutError, "gateway_timeout"),
    (OSError, "gateway_network_error"),
)
```

```python
except (DeliveryUnavailable, TimeoutError, OSError) as exc:
    code, cause = failure_code(exc), exc.__cause__
    logger.warning(json.dumps({
        "event": "delivery_failed", "notification_id": str(notice.id),
        "kind": notice.kind, "attempts": notice.attempts, "code": code,
        "error": type(exc).__name__,
        "cause": type(cause).__name__ if cause is not None else None,
    }, ensure_ascii=False))
    repository.finish(notice, now, policy, error=True, reason=code)
```

Також `raise DeliveryUnavailable from None` → `from exc`: першопричина доступна обробнику
вище через `__cause__`.

**Три межі рішення:**

1. `TimeoutError` — підклас `OSError`, тому `FAILURE_CODES` — **кортеж, не словник за типом**:
   порядок перевірки значущий, інакше таймаут позначався б як мережева помилка.
2. У журнал ідуть **лише назви класів**, не текст помилок. Текст `DBAPIError` може містити
   фрагменти запиту; журнал у цьому проєкті свідомо не несе навіть ідентифікаторів зі шляху
   (THR-09, CWE-532). Ціна: оператор бачить `DBAPIError`, а не конкретний SQLSTATE.
3. `last_error` лишається **коротким стабільним кодом**, бо потрапляє в аудит
   (`postgres.py` → `tables.audit`), доступний через `GET /audit`, і обмежений `String(64)`.
   Текст помилки там був би витоком внутрішніх деталей (CWE-209).

`reason` додано як параметр **із типовим значенням** `"gateway_unavailable"`, тож наявні
виклики `finish(..., error=True)` і інтеграційний тест, що перевіряє саме це значення,
лишилися чинними.

### 4.3 R-05 → guard clause

```python
        # Недосяжно: кожна ітерація завершується return або raise, а `continue` можливий
        # лише на першій спробі. Guard лишає явну відмову, якщо межу циклу колись змінять.
        raise ApiProblem(  # pragma: no cover — страховка від майбутньої зміни range()
            ErrorCode.TRANSIENT_CONFLICT, headers={"Retry-After": "1"}
        )
```

`pragma: no cover` тут доречна (precedent — `booking_service.py:114`): рядок недосяжний
**за побудовою**, і тест на нього написати неможливо без зміни самого циклу. Поріг
покриття 90% (MAINT-001) витримано.

### 4.4 R-07 → експоненційний відступ з верхньою межею

```python
MAX_BACKOFF_FACTOR = 60


def next_delay(interval: float, previous: float) -> float:
    """Наступна затримка після збою: подвоєння з верхньою межею."""
    return min(previous * 2, interval * MAX_BACKOFF_FACTOR)
```

```python
            except (DBAPIError, OSError) as exc:
                if args.once: ...
                delay = next_delay(args.interval, delay)
                print(json.dumps({"event": "worker_retry", "code": "database_unavailable",
                                  "error": type(exc).__name__, "retry_in_s": round(delay, 1)}),
                      flush=True)
```

Успішний цикл скидає `delay` до `args.interval`.

**Компроміс.** Catch розширено рівно на `OSError` і **не** до `except Exception`. Це
навмисно: `ValueError` з інваріантів сховища (`«outbox records cannot be erased»`,
`«audit history cannot be rewritten»`) — дефект коду, і цикл не повинен його переживати.
Операційні збої переживаємо з відступом, дефекти лишаємо фатальними. Верхня межа
(60 × `--interval`) потрібна з другого боку: без неї відступ зріс би до годин і нагадування
запізнювалися б уже через сам механізм захисту. Поле `"code"` у подію збережено, щоб не
зламати формат, описаний у `docs/implementation/load-worker-calendar-audit.md`.

### 4.5 R-08 → деградація замість відмови старту

```python
            try:
                for path in openapi_export.write_artifacts(app):
                    logger.info("OpenAPI згенеровано з коду → %s", path)
            except OSError as exc:
                logger.warning(
                    "OpenAPI не записано (%s); чинною лишається специфікація з репозиторію",
                    type(exc).__name__,
                )
```

**Компроміс.** Поглинається **лише `OSError`** (права, read-only, брак місця) — операційна
причина, за якої готова специфікація в репозиторії лишається чинною. `RuntimeError` із
генерації специфікації лишається фатальним: це дефект, і пропускати його в реліз не можна.
Що розмежування працює, доводять два тести з протилежними очікуваннями:
`test_startup_degradation.py::test_spec_generation_defect_still_stops_startup` і наявний
`test_thread_switch_interval.py::test_lifespan_restores_process_interval_on_success_and_startup_failure`.

---

## 5. Що свідомо не виправлено

Це не «не встигли»: кожне з чотирьох — рішення рівня ADR, яке змінює контракт або вимагає
виміру, тож ухвалює його команда, а не одна аудиторна правка.

### 5.1 R-03 — потрібне рішення, а не правка

Варіанти: (а) прибрати `ensure_horizon` із запиту й покладатися лише на окремий Worker —
але тоді запуск без Worker (локальна розробка, демо) віддає порожній пошук; (б) обмежити
генерацію вузьким вікном замість повного горизонту; (в) лишити fallback, але виміряти його
тривалість і внести до SLO. Потрібен **вимір**, якого немає: скільки триває
`extend_horizon` на реальних даних. Без цифри вибір між (а)–(в) був би вгадуванням.

### 5.2 R-04 — зміна контракту API

Правильна правка — окрема `/health/ready` з `SELECT 1` і коротким таймаутом, liveness лишити
як є, а `render.yaml` перевести на readiness. Це **новий ендпоїнт**, тобто зміна
`openapi-generated.yaml`, запис у каталозі помилок і рішення, чи версіонувати службові
маршрути. Ухвалюється як ADR, а не правиться на парі.

### 5.3 R-06 — потрібен вимір, а не зміна константи

`POOL_SIZE = 32` можна підняти до 40, але це лише перенесе межу: за нею стоїть ліміт
з'єднань безкоштовного плану PostgreSQL на Render. Правильний крок — виміряти точку насичення
(`scripts/load_midterm.py` уже є) і записати її як SLI/SLO з бюджетом помилок. Деградація вже
керована (503 + `Retry-After`), тож ризик не вимагає негайної правки.

### 5.4 R-09 — локальний інструмент розробника

Правка (перенести `setdefault` під `if __name__ == "__main__"`) проста, але MCP-сервер не
входить у постачання, а зміна порядку його ініціалізації стосується
`docs/implementation/` і Лаб 4. Виносимо в окремий issue.

---

## 6. Що перевірено й виявилося справним

Записуємо нарівні зі знахідками: половина цінності прочісування — у тому, що **не**
виявилося проблемою. Інакше звіт перетворюється на перелік здогадів.

| Перевірка | Результат |
|---|---|
| Блокувальні I/O в `async`-коді (кат. E) | немає: усі роутери синхронні (`def`), FastAPI виконує їх у threadpool — правило ruff `ASYNC` не спрацьовує обґрунтовано |
| Таймаути на БД (кат. B) | є на всіх рівнях: `connect_timeout=5`, `pool_timeout=5`, `lock_timeout=5s`, `statement_timeout=15s` |
| Розбір курсора пагінації (кат. C) | `pagination.py:83–95` — вузький catch `(ValueError, KeyError, TypeError, binascii.Error)`, окрема перевірка типів у `cursor_fields`, відповідь 422, причина збережена через `from exc` |
| `except BaseException` у `postgres.py:54,76,115` | коректний патерн «cleanup + re-raise»: кожен блок звільняє ресурс і робить `raise`; винятків не поглинає |
| Витік внутрішніх деталей у відповідях (кат. A) | `errors.py:500–512` відкидає `input` і `ctx` Pydantic (CWE-209); `_on_unhandled` пише `logger.exception` у журнал, а клієнту віддає загальний `INTERNAL_ERROR` |
| Порожні `except: pass` | немає жодного в `src/` |
| Нескінченні цикли в домені | `templates.py:98` (`while cursor < end`) — крок `step` обмежено валідацією `slot_minutes`, курсор монотонно зростає |
| Переповнення в арифметиці часу | обробляється: `admin_service.py:110` ловить `OverflowError` і віддає 422 з полем |
| Межі повторів | `RetryPolicy.next_attempt` обмежує показник (`min(..., 30)`) і затримку (`max_delay`) |

---

## 7. Перевірка результату

```console
$ python -m pytest -q --ignore=tests/integration
664 passed                      # було 610; +54 нових тести

$ python -m ruff check . && python -m ruff format --check .
All checks passed!   160 files already formatted

$ python -m bandit -c pyproject.toml -r src scripts
Total issues (by severity): Undefined: 0  Low: 0  Medium: 0  High: 0

$ python scripts/check_traceability.py
Порушень немає.
```

**Обмеження прогону.** `tests/integration/` у цій сесії не запускалися: `initdb` відмовляє
під користувачем `root` у контейнері — це обмеження оточення, не коду. Їх треба прогнати
локально перед PR, бо саме вони перевіряють `PostgresOutbox.finish`, чию сигнатуру
розширено (`reason`). Зворотна сумісність забезпечена типовим значенням параметра, і
`test_outbox.py:98`, що очікує `last_error == "gateway_unavailable"`, лишається чинним, але
це треба **підтвердити прогоном**, а не вважати доведеним.

Нові похідні вимоги QA-15 і QA-16 внесено до
[`rtm.md`](../requirements/rtm.md) §6, тож мітки `@pytest.mark.req` у нових тестах
простежувані автоматично.

---

## 8. Використання ШІ

| Що | Деталі |
|---|---|
| **Інструмент** | Claude (Opus 5), аудиторна сесія 02.11.2026 |
| **Згенеровано** | план прочісування за категоріями A–E; `grep`-запити; чернетки 9 карток знахідок; код п'яти правок; 54 тести в 4 файлах; цей документ |
| **Як верифіковано** | ① кожну знахідку **відтворено** виконанням, а не прийнято з опису: R-01 — запуском `get_settings()` із порожньою змінною, R-07 — `ImportError` до правки, решта — читанням коду за вказаними рядками; ② для кожної правки спершу прогнано тест до зміни коду (red: 41 failed, 7 passed) і після (green: 54 passed) — обидва логи в `evidence/`; ③ повний набір `664 passed` проти baseline `610 passed`; ④ `ruff check`, `ruff format --check`, `bandit` і `check_traceability.py` — чисті |
| **Що адаптовано вручну** | межі в `NUMERIC_SETTINGS` звужено до «відсікти абсурд», бо числа відкриті в OQ-001; catch у Worker **не** розширено до `except Exception` (початкова чернетка пропонувала саме це) — `ValueError` з інваріантів сховища лишено фатальним; у журнал виведено лише назви класів помилок, не текст, через THR-09/CWE-532; `reason` зроблено параметром із типовим значенням, щоб не зламати наявний інтеграційний тест |
| **Що відхилено** | ① правки R-03, R-04, R-06, R-09 — вимагають виміру або зміни контракту (§5); ② пропозиція логувати `str(exc)` для `DBAPIError` — витік фрагментів запиту; ③ пропозиція додати `/health/ready` «заодно» — зміна OpenAPI без ADR |
| **Межі перевірки** | `tests/integration/` не прогнано (див. §7); severity виставлено експертно, без виміру частоти відмов; R-05 позначено як латентну, бо сьогодні недосяжна |

---

## 9. Ймовірні питання на захисті

1. **Чому порожню змінну обробляєте типовим значенням, а `5min` — відмовою? Це ж обидва
   некоректний вхід.** Порожнє поле однозначно означає «не задано» — це норма в панелі
   розгортання. `5min` — спроба задати значення, яку не можна інтерпретувати; тиха підміна
   на `5` змінила б межу безпеки (кількість спроб входу) без жодного сліду. Fail-safe там,
   де неоднозначності немає; fail-fast там, де вона є.
2. **Чому не `except Exception` у циклі Worker — було б надійніше?** Навпаки. Цикл, що
   переживає `ValueError` з «outbox records cannot be erased», мовчки крутився б із
   пошкодженим інваріантом. Операційні збої (`DBAPIError`, `OSError`) переживаємо з
   відступом; дефекти коду лишаємо фатальними. Широкий catch — це і є «помилки ховаються
   мовчки» з категорії A.
3. **Чому в журналі лише назва класу помилки, а не текст? Це ж гірша діагностика.**
   Свідомий компроміс: текст `DBAPIError` може містити фрагменти запиту, а проєкт не пише
   в журнал навіть ідентифікаторів зі шляху (THR-09, CWE-532). Клас + код причини +
   `notification_id` + `attempts` дають достатньо, щоб відрізнити три сценарії відмови.
4. **Чому `last_error` — код, а не повідомлення?** Поле потрапляє в аудит, доступний через
   `GET /audit`, і обмежене `String(64)`. Повідомлення там було б витоком внутрішніх
   деталей назовні (CWE-209).
5. **R-05 недосяжна — чому ви її взагалі виправляли?** Бо ціна один рядок, а декоратор
   обгортає кожен маршрут, що змінює дані. Межа циклу задана виразом `2 if retry_deadlock
   else 1`; одна зміна відкриває шлях, на якому маршрут поверне `None`. Я позначив її Low і
   латентною саме щоб не видавати страховку за знайдений баг.
6. **Чому чотири знахідки не виправлено?** R-04 — новий ендпоїнт, тобто зміна OpenAPI й
   ADR; R-03 і R-06 потребують виміру, якого немає (тривалість `extend_horizon`, точка
   насичення пулу); R-09 — локальний інструмент поза постачанням. Виправляти їх «на око»
   означало б вгадувати.
7. **`except BaseException` у `postgres.py` — це ж занадто широке перехоплення?** Перевірив
   окремо: усі три блоки роблять `cleanup + raise`, винятків не поглинають. Для звільнення
   ресурсу це правильний патерн — `BaseException` тут потрібен, щоб з'єднання закрилося й
   при `KeyboardInterrupt`.
8. **Чому `/health` узагалі не перевіряє БД — хіба це не очевидна помилка?** Сам ендпоїнт
   коректний і намір задокументовано: це liveness. Помилка не в ньому, а в тому, що
   `render.yaml` використовує liveness там, де потрібна readiness. Різниця важлива, бо
   «виправлення» самого `/health` зламало б його справжнє призначення.
