# Тимчасова публічна демонстрація з локального ПК

Публічна адреса й дата перевірки наведені в [README](../../README.md#публічне-розгортання).
API, PostgreSQL і Worker працюють на Windows; localhost.run передає HTTPS-запити
через SSH на API, який слухає тільки `127.0.0.1:3001`.
Окремий порт дає змогу зберегти локальний профіль на 3000 для роботи команди.

## Підготовка

1. Запустити власну PostgreSQL і застосувати міграції за
   [нативною інструкцією](../implementation/native-launch-checklist.md).
2. Створити ігнорований Git файл `.env.public.local` із runtime URL тієї самої БД.
   Роль БД — `unislot_app`, а не власник схеми. Додати:

   ```text
   UNISLOT_DEMO_AUTH=0
   UNISLOT_EXPORT_OPENAPI=0
   UNISLOT_SESSION_COOKIE_SECURE=1
   UNISLOT_CORS_ORIGINS=https://поточне-ім'я-тунелю
   ```

   Останнє значення потрібно замінити точною HTTPS-адресою, яку видає SSH-тунель.
   Після зміни адреси перезапустити API. Це явний дозволений Origin для входу й CSRF;
   wildcard не використовувати. Секретний URL БД у Git не додавати.

## Запуск

З кореня репозиторію, перший термінал:

```powershell
.\.venv\Scripts\python.exe -m uvicorn api.main:app --app-dir src --env-file .env.public.local --workers 2 --host 127.0.0.1 --port 3001 --proxy-headers --forwarded-allow-ips 127.0.0.1
```

Другий термінал, якщо Worker цієї БД ще не працює:

```powershell
.\.venv\Scripts\python.exe -X utf8 scripts/run_worker.py --env-file .env.local
```

Третій термінал:

```powershell
ssh -T -o ServerAliveInterval=30 -o ExitOnForwardFailure=yes -R 80:127.0.0.1:3001 nokey@localhost.run
```

SSH покаже адресу тунелю. Унести її до `UNISLOT_CORS_ORIGINS` та README після
зовнішньої перевірки. Для вільного домену акаунт і ключ не потрібні; HTTPS
термінується на стороні localhost.run, а до ПК трафік іде через SSH.
Деталі: [HTTP-тунелі](https://localhost.run/docs/http-tunnels),
[безкоштовний доступ](https://localhost.run/docs/forever-free),
[підключення без ключа](https://localhost.run/docs/faq#i-dont-want-to-use-an-ssh-key).

API довіряє proxy-заголовкам лише від локального тунелю. Swagger використовує
відносну базову адресу `/`, тому Try it out працює з тим самим HTTPS-сервером;
локальна адреса `http://localhost:3000` доступна як окремий варіант у Servers.

## Перевірка

Перевірити через публічну адресу:

- `/health`, `/`, `/api-docs`, статичні файли й `/openapi.json` — 200;
- реєстрацію, парольний вхід, Secure/HttpOnly cookie й власний профіль;
- пошук слотів студентом і відмову 403 для адміністративних операцій;
- відмову 401 без сесії та з відкритим `demo-admin`;
- відмову 403 без CSRF або з чужим Origin, вихід і відкликання сесії.

Власник передає викладачу облікові дані тестових провайдера й адміністратора окремо.
Паролі, session cookie та URL БД не публікуються в README.

## Доступність

Посилання працює, доки ввімкнений ПК і запущені потрібні процеси. Після зупинки
SSH тунель недоступний; новий запуск або ротація безкоштовного домену може змінити
адресу. Безкоштовний план має обмеження швидкості та строку існування домену.
Для тривалого хостингу є окрема [конфігурація Render](render.md).
