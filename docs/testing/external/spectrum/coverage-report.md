# Звіт про покриття тестами: `spectrum-app`

**Репозиторій:** [`ukma-fin-ssdm-2026/Spectrum-project`](https://github.com/ukma-fin-ssdm-2026/Spectrum-project)
**Гілка:** `feat/ttd` · **Комміт:** `43da8d7` · **Дата:** 2026-10-12 · **Обсяг:** ~707 рядків Java у 44 файлах

Активність «Test-a-Thon»: написання модульних тестів, підключення інструменту покриття
й аналіз прогалин. Журнал налагодження — окремим документом,
[`debugging-log.md`](debugging-log.md).

---

## 1. Інструмент покриття

До цієї сесії у збірці не було жодного інструменту вимірювання покриття. Додано
`jacoco-maven-plugin` `0.8.14` у `spectrum-app/pom.xml`:

| Виконання       | Фаза         | Що робить                                                      |
|-----------------|--------------|----------------------------------------------------------------|
| `prepare-agent` | `initialize` | Під'єднує агент покриття й визначає властивість `argLine`      |
| `report`        | `test`       | Пише HTML/XML/CSV у `spectrum-app/target/site/jacoco`          |
| `check`         | `verify`     | Валить збірку нижче порогів із таблиці нижче                   |

Згенерований CDI-обв'яз (`*_Bean`, `*_ClientProxy`, `*_Subclass`) виключено, щоб цифри
описували наш код, а не внутрішню кухню Quarkus.

| Область правила | Лічильник | Мінімум |
|-----------------|-----------|---------|
| `BUNDLE`        | `LINE`    | 80 % |
| `BUNDLE`        | `BRANCH`  | 70 % |
| `CLASS` (крім `*Controller`) | `LINE` | 50 % |

Окреме правило на рівні класу потрібне тому, що загальний поріг по бандлу маскує саме
той випадок, який ми шукаємо: клас без жодного тесту розчиняється в середньому.

`prepare-agent` водночас розв'язує проблему, що існувала до нас: `maven-surefire-plugin`
і `maven-failsafe-plugin` уже були налаштовані з `<argLine>@{argLine}</argLine>`, але
жоден плагін у збірці цієї властивості не визначав (знахідка **F-5**).

Запуск:

**Linux / macOS**

```shell
cd spectrum-app
./mvnw clean verify
```

**Windows (PowerShell)**

```powershell
cd spectrum-app
.\mvnw clean verify
```

Звіт — у `spectrum-app/target/site/jacoco/index.html`. Щоб отримати звіт без падіння
збірки на порогах, достатньо `./mvnw clean test`.

> **Відсотки ще не заповнені — свідомо.** Середовище, у якому готувався цей документ,
> не мало доступу до Maven Central, тож набір тестів не було виконано. Відповідальний
> за покриття запускає `./mvnw clean verify` на парі й вставляє підсумок по бандлу в
> таблицю нижче. Решта документа — результат читання коду й не залежить від прогону.

| Метрика           | До  | Після |
|-------------------|-----|-------|
| Рядки (line)      |     |       |
| Гілки (branch)    |     |       |
| Методи (method)   |     |       |
| Тестових методів  | 17  | 136   |
| Тестових класів   | 7   | 16    |

---

## 2. Базовий стан

Сім тестових класів, 17 тестових методів — усі на шарі відображення та сервісів:

| Тестовий клас                    | Клас під тестом              |
|----------------------------------|------------------------------|
| `HotelAddressFactoryTest`        | `HotelAddressFactory`        |
| `HotelFactoryTest`               | `HotelFactory`               |
| `HotelSearchCriteriaFactoryTest` | `HotelSearchCriteriaFactory` |
| `HotelServiceImplTest`           | `HotelServiceImpl`           |
| `AuthServiceImplTest`            | `AuthServiceImpl`            |
| `UserFactoryImplTest`            | `UserFactoryImpl`            |
| `TokenFactoryImplTest`           | `TokenFactoryImpl`           |

---

## 3. Аналіз прогалин

Прогалини згрупувалися в одному місці: **непокритим виявилося все, що в наявних тестах
підміняли моки.** `HotelServiceImplTest` мокає `HotelRepository`, тому власна логіка
репозиторію — фільтрація, сортування й пагінація, найщільніше розгалуження в усьому
застосунку — жодного разу не виконувалася тестом.

Це системна властивість, а не випадковість: мок означає «цю поведінку перевірять десь
інде», і якщо того «десь інде» не існує, прогалина лишається невидимою саме там, де код
найскладніший.

| Клас | Рядків коду | Точок розгалуження | Тестів до | Ризик, якщо помилка |
|------|------------:|-------------------:|-----------|---------------------|
| `HotelRepositoryStub`       | 47 | 9 | **немає** | Хибні результати пошуку, мовчки |
| `PageResponse`              | 63 | 4 | **немає** | Клієнт не може дістатися частини даних |
| `HotelController`           | 70 | 4 | **немає** | Хибні коди відповіді |
| `AuthController`            | 63 | 0 | **немає** | Куки токена втрачають захисні атрибути |
| `ValidationExceptionMapper` | 19 | 2 | **немає** | Непридатні для використання тіла помилок |
| `UserRepositoryStub`        | 12 | 0 | **немає** | Дублікати акаунтів |
| `GetHotelsParams`           | 58 | 0 | **немає** | `NullPointerException` на відсутньому фільтрі |
| Обмеження DTO (`Address`, `CreateHotel`, `Money`, `RegisterRequest`, `LoginRequest`, `PaginationParams`) | 63 | 0 | **немає** | Некоректний ввід доходить до домену |
| Компактні конструктори `HotelRecord`, `HotelSearchCriteria`, `HotelSearchPage` | 32 | 0 | **немає** | Спільний змінюваний стан витікає назовні |

---

## 4. Що додано

119 нових тестових методів у дев'яти файлах:

| Файл | Тестів | На чому зосереджено |
|------|-------:|---------------------|
| `logic/hotel/HotelRepositoryStubTest`      | 27 | Кожен фільтр окремо й у комбінації, включність меж, масштаб `BigDecimal`, впорядкування за рейтингом, offset/limit, `count` проти розміру сторінки, пошук і перезапис |
| `api/RequestValidationTest`                | 29 | Усі обмеження Bean Validation на шести DTO запитів, на межі й за межею |
| `api/common/page/PageResponseTest`         | 12 | Округлення `totalPages` на 11 випадках плюс вичерпний перебір 0–60 × 1–12, захисне копіювання, семантика значення |
| `api/auth/AuthControllerTest`              | 11 | 201/409 і 200/401, а також п'ять атрибутів куки `access_token` |
| `logic/hotel/HotelDomainRecordsTest`       |  9 | Копіювання й обробка `null` у компактних конструкторах трьох доменних записів |
| `logic/hotel/HotelServiceImplTest` (розширено) | +5 | Арифметика зміщення, переповнення в `Math.multiplyExact`, делегування `findById` |
| `api/common/error/ValidationExceptionMapperTest` | 6 | Обрізання шляху властивості, відображення кількох порушень, статус 400 |
| `logic/auth/UserRepositoryStubTest`        |  6 | Семантика `putIfAbsent` для дублікатів |
| `api/hotel/HotelControllerTest`            |  6 | 201/200/404 і сторінка, яку збирає контролер |
| `api/hotel/GetHotelsParamsTest`            |  4 | Нормалізація `?amenity=` з `null` у порожній список |
| `api/hotel/HotelSearchCriteriaFactoryTest` (розширено) | +4 | Порожні й дубльовані зручності, невстановлені фільтри, проброс пагінації |

Окремо варто пояснити два підходи, застосовані в цих тестах.

**Інваріант замість переліку прикладів.** У `PageResponseTest` поряд із таблицею
конкретних випадків є перебір, який стверджує `totalPages * limit >= totalItems` для
всіх комбінацій 0–60 елементів і 1–12 на сторінку. Приклади ловлять лише те, що хтось
здогадався перелічити; інваріант ловить весь клас помилок округлення — зокрема той,
що став основою челенджу з налагодження.

**Фіксація поточної поведінки.** Три тести закріплюють те, що виглядає дефектом, а не
стверджують, що воно правильне: `findByNameIsCaseSensitive`,
`createPropagatesTheDuplicateNameFailure`,
`yieldsAnEmptyPointerForAViolationOnTheParameterItself`. Кожен у `@DisplayName`
посилається на свою знахідку нижче. Коли дефект виправлять, тест впаде — і це задумано:
так зміна поведінки стає помітною в огляді, а не проходить мовчки.

---

## 5. Знахідки

Написання тестів виявило вісім проблем. Три варті окремої issue, решту варто щонайменше
зафіксувати.

| ID | Критичність | Де | Знахідка |
|----|-------------|-----|----------|
| **F-1** | Низька | `ValidationExceptionMapper` | Порушення на самому тілі запиту (`@Valid @NotNull CreateHotel request`) дає шлях `create.request`. `skip(2)` з'їдає обидва вузли, тож клієнт отримує `{"path": "", "message": "must not be null"}` без жодної вказівки на поле. Зафіксовано тестом `yieldsAnEmptyPointerForAViolationOnTheParameterItself`. |
| **F-2** | Середня | `HotelRepositoryStub.findByName` | Пошук за назвою використовує `equals`, тоді як збіг за містом — `equalsIgnoreCase`. `HotelServiceImpl.save` покладається на `findByName` як на захист від дублів, тому «Grand Budapest» і «grand budapest» обидва приймаються як нові готелі. Зафіксовано тестом `findByNameIsCaseSensitive`. |
| **F-3** | **Висока** | `HotelController.create` | `HotelServiceImpl.save` кидає `HotelAlreadyExistsException`, її ніхто не ловить і жодного `ExceptionMapper` для неї не зареєстровано — тож дубль назви готелю повертає **500**, а не 409. `AuthController` ту саму ситуацію з `EmailAlreadyRegisteredException` обробляє правильно, тобто це непослідовність, а не свідоме рішення. У специфікації OpenAPI для `POST /v1/api/hotels` код 409 теж не оголошено. Зафіксовано тестом `createPropagatesTheDuplicateNameFailure`. |
| **F-4** | **Висока** | `.github/workflows/github-actions-test.yml` | Завдання «CI Test» виконує `echo "Hello, World!"`. Жоден workflow не запускає `mvn test`, тож зелений бейдж у README не засвідчує нічого. Для Spotless і SpotBugs реальні гейти є, для тестів — ні. |
| **F-5** | Середня | `spectrum-app/pom.xml` | Surefire і Failsafe посилалися на `@{argLine}`, якої ніщо не визначало. Виправлено додаванням `prepare-agent` від JaCoCo. |
| **F-6** | Середня | `HotelServiceImpl.save` + `HotelRepositoryStub.add` | Класичний check-then-act: спершу `findByName`, потім `add`. `add` — це звичайний `put` за щойно згенерованим `UUID`, тому два одночасні створення з однаковою назвою обидва успішні. `UserRepositoryStub.add` ту саму задачу розв'язує через `putIfAbsent` і повертає `boolean`; на боці готелів цього немає. |
| **F-7** | Низька | `HotelRepositoryStub.filtered` | `checkIn` і `checkOut` валідуються, відображаються в `HotelSearchCriteria` — і далі не використовуються. Фільтри за датами мовчки ігноруються, хоча API їх оголошує. |
| **F-8** | Низька | `HotelFactory.create(CreateHotel)` | Щойно створений готель жорстко отримує `pricePerNight = 0`, `rating = 0`, `amenities = {}`, тож ніколи не потрапить під фільтр `minPrice` чи `minRating`. Очікувано на стадії заглушки, але означає, що шляхи створення й пошуку поки неможливо перевірити наскрізно. |

---

## 6. Чого тести свідомо не покривають

За пріоритетом:

1. **Тести на рівні HTTP.** Усе написане працює на звичайних об'єктах. Серіалізація,
   узгодження кодів відповіді, зв'язування `@BeanParam` і сам факт виклику
   `ValidationExceptionMapper` лишаються неперевіреними. `rest-assured` уже є серед
   тестових залежностей — наступний крок саме тут: тести ендпоінтів через
   `@QuarkusTest`. Їм знадобиться `JWT_SECRET` у
   `spectrum-app/src/test/resources/application.properties`, бо `TokenFactoryImpl`
   вимагає цю властивість конфігурації на старті.
2. **Конкурентність.** Обидві заглушки використовують конкурентні мапи, але жоден тест
   не перевіряє їх під навантаженням. F-6 — саме той дефект, який упіймав би
   конкурентний тест.
3. **`CreateRoom`, `Room`, `RoomType`, `RoomStatus`.** Жоден контролер їх поки не
   споживає; у знаменнику покриття вони будуть мертвим вантажем, доки не з'явиться
   функціональність кімнат.
4. **Мутаційне тестування.** Покриття рядків каже, що рядок виконався, а не що
   якесь твердження помітило б його зміну. PIT (`org.pitest:pitest-maven`) по
   `logic.hotel` — природне продовження, щойно гейт із пункту 1 стане зеленим.

---

## 7. Рекомендована наступна дія

Зробити гейт справжнім — замінити заглушку CI на завдання, що виконує
`./mvnw -B clean verify`, щоб і пороги JaCoCo, і сам набір тестів блокували злиття
(**F-4**). Доки цього немає, відсотки з розділу 1 — знімок стану, а не гарантія.

Готова заміна для `.github/workflows/github-actions-test.yml`, у тій самій формі, що й
наявні workflow для Spotless і SpotBugs:

```yaml
name: CI Test

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
        with:
          fetch-depth: 0

      - uses: actions/setup-java@v4
        with:
          distribution: temurin
          java-version: 21
          cache: maven

      - name: Permissions for mvnw
        working-directory: spectrum-app
        run: chmod +x mvnw

      - name: Run tests and coverage gates
        working-directory: spectrum-app
        run: ./mvnw -B clean verify

      - name: Upload coverage report
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: jacoco-report
          path: spectrum-app/target/site/jacoco
```

---

## Використання ШІ

- **Згенеровано:** код модульних тестів, конфігурація JaCoCo у `pom.xml`, структура та
  чернетка формулювань цього документа.
- **Інструмент:** Claude (Opus 5), веб-інтерфейс.
- **Верифікація:** синтаксис усіх 16 тестових файлів перевірено парсером, `pom.xml` —
  на коректність XML; жодного рядка понад 100 колонок (ліміт google-java-format, який
  перевіряє Spotless). Знахідки F-1…F-8 звірено з вихідним кодом за коммітом `43da8d7`
  поіменно: клас, метод, рядок. Набір тестів **не було скомпільовано й запущено** —
  середовище не мало доступу до Maven Central; це явно зазначено в розділі 1, а
  відсотки покриття лишені незаповненими.
- **Заповнено вручну:** вибір порогів покриття, класифікація критичності знахідок,
  пріоритизація у розділі 6.
