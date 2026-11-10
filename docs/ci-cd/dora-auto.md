# Метрики DORA — автоматичний розрахунок

> Згенеровано `scripts/dora_metrics.py` (Лаб 10, бонус 1). Не редагуйте вручну —
> перезапустіть команду нижче.

- **Репозиторій:** `ukma-fin-ssdm-2026/SSDM_12` · **гілка:** `main` · **подія:** `push` · **workflow:** `CI`
- **Вікно:** 2026-10-19T00:00:00Z — 2026-11-09T00:00:00Z (21 дн., межа праворуч не включена)
- **Дані зібрано:** 2026-11-10T16:19:34Z
- **Команда:** `python scripts/dora_metrics.py --since 2026-10-19 --until 2026-11-09 --repo ukma-fin-ssdm-2026/SSDM_12 --branch main --event push --workflow CI --transport gh --dataset docs/ci-cd/evidence/dora-dataset.json --out docs/ci-cd/dora-auto.md --json docs/ci-cd/dora-auto.json`

## 1. Чотири метрики

| Метрика | Формула | Результат | Рівень DORA 2025 → Top % |
|---|---|---|---|
| Частота розгортань | зелені запуски / тижні вікна | **32,0 / тиждень** (4,6 / добу); зелених 96 | на вимогу (кілька разів на день) → 16,2 % |
| Час виконання змін | перший коміт PR → завершення зеленого запуску з комітом | медіана **1,56 год** · середнє 5,38 год · p90 12,2 год (змін: 104) | менше доби → 24,4 % |
| Частота збоїв змін | червоні / усі завершені | **5,8 %** (6 / 104); без скасованих — 5,9 % | 4–8 % → 36,2 % |
| Час відновлення | червоний → наступний зелений (завершення) | медіана **124 хв** · середнє 316 хв (випадків: 6) | менше доби → 56,5 % |

Запусків у вікні: 104 — зелених 96, червоних 6, скасованих 2.

## 2. Черга й виконання в часі виконання змін

| Складова | Медіана, хв | Середнє, хв | Частка суми часу виконання змін |
|---|--:|--:|--:|
| Робота в гілці (1-й коміт → відкриття PR) | 2,2 | 101,7 | — |
| Очікування рев'ю (відкриття → злиття PR) | 56,8 | 185,4 | — |
| **Черга CI** | 0,05 | 6,9 | **2,15 %** |
| **Виконання CI** | 5,4 | 5,8 | **1,79 %** |

Черга й виконання взято з того зеленого запуску, що завершив відлік зміни.
Змін, чий власний запуск не був зеленим (доїхали з наступним зеленим): 8.

Розподіл часу виконання змін за рівнями DORA: менше години — 37; менше доби — 65; від доби до тижня — 2

## 3. Телеметрія CI проти орієнтирів CircleCI

| Показник | Орієнтир | Наше значення |
|---|---|---|
| Успішність запусків на основній гілці | 90 % | 92,3 % |
| Повернення основної гілки до зеленого | до 60 хв | медіана 124 хв |
| Тривалість запуску workflow | до 10 хв | медіана 5,4 хв, p90 10,0 хв |
| Черга (довідково) | — | медіана 0,05 хв, p90 8,7 хв |

## 4. Перевірки чутливості

| Варіант | Значення |
|---|---|
| Частота розгортань за строгим прочитанням рівня «від разу на годину до разу на добу» (для 1–24 розгортань на добу) | 4,6 / добу → 22,7 % |
| Частота збоїв без скасованих у знаменнику | 5,9 % |
| Відновлення по інцидентах (червоні поспіль — один випадок) | 5 інцидентів; медіана 114 хв, середнє 232 хв |
| Рівень спроб (кожен re-run — окремий прогін) | спроб 106, червоних 8; частота збоїв 7,5 %; відновлень 8, медіана 145 хв, середнє 309 хв |

## 5. Запуски на гілці, що мали повторні спроби (re-run)

| Запуск | Коміт | PR | Спроби | Позеленів без зміни коду |
|---|---|---|---|---|
| [40672926847](https://github.com/ukma-fin-ssdm-2026/SSDM_12/actions/runs/40672926847) | `580dbf8` | #213 | 1: failure (28.10 12:42) → 2: success (28.10 19:38) | **так** |
| [41328893623](https://github.com/ukma-fin-ssdm-2026/SSDM_12/actions/runs/41328893623) | `8305b69` | #241 | 1: failure (01.11 19:06) → 2: failure (01.11 19:29) | ні |

## 6. Запуски (час — Київ)

| № | Коміт | PR | Перший коміт PR | Запуск завершено | Черга, хв | Виконання, хв | Статус | Спроб |
|--:|---|--:|---|---|--:|--:|:--:|--:|
| 1 | [`4f0b4f0`](https://github.com/ukma-fin-ssdm-2026/SSDM_12/actions/runs/39265692484) | #133 | 19.10 10:21 | 19.10 17:23 | 8,7 | 9,7 | ✅ | 1 |
| 2 | [`526eb9f`](https://github.com/ukma-fin-ssdm-2026/SSDM_12/actions/runs/39271395143) | #134 | 19.10 16:24 | 19.10 17:44 | 0,1 | 1,5 | ✅ | 1 |
| 3 | [`170fd85`](https://github.com/ukma-fin-ssdm-2026/SSDM_12/actions/runs/39274189575) | #136 | 19.10 17:50 | 19.10 18:02 | 0,0 | 1,5 | ✅ | 1 |
| 4 | [`e286df0`](https://github.com/ukma-fin-ssdm-2026/SSDM_12/actions/runs/39274254041) | #138 | 19.10 17:55 | 19.10 18:04 | 1,1 | 1,4 | ✅ | 1 |
| 5 | [`c3badd6`](https://github.com/ukma-fin-ssdm-2026/SSDM_12/actions/runs/39298553141) | #139 | 19.10 17:50 | 19.10 21:00 | 0,1 | 2,4 | ✅ | 1 |
| 6 | [`67ced02`](https://github.com/ukma-fin-ssdm-2026/SSDM_12/actions/runs/39421790350) | #141 | 20.10 01:44 | 20.10 15:24 | 0,1 | 1,7 | ✅ | 1 |
| 7 | [`a1e371e`](https://github.com/ukma-fin-ssdm-2026/SSDM_12/actions/runs/39423402607) | #143 | 20.10 11:45 | 20.10 15:36 | 0,1 | 1,5 | ✅ | 1 |
| 8 | [`ab43317`](https://github.com/ukma-fin-ssdm-2026/SSDM_12/actions/runs/39490827542) | #144 | 20.10 22:24 | 20.10 23:32 | 2,8 | 11,5 | ✅ | 1 |
| 9 | [`97ffd59`](https://github.com/ukma-fin-ssdm-2026/SSDM_12/actions/runs/39493186229) | #145 | 20.10 22:41 | 20.10 23:36 | 0,0 | 2,0 | ✅ | 1 |
| 10 | [`6593b35`](https://github.com/ukma-fin-ssdm-2026/SSDM_12/actions/runs/39625878630) | #160 | 21.10 14:20 | 21.10 18:29 | 0,1 | 1,9 | ✅ | 1 |
| 11 | [`74354bb`](https://github.com/ukma-fin-ssdm-2026/SSDM_12/actions/runs/39663686908) | #161 | 21.10 18:50 | 21.10 22:42 | 0,1 | 1,7 | ✅ | 1 |
| 12 | [`a62cc94`](https://github.com/ukma-fin-ssdm-2026/SSDM_12/actions/runs/39800385722) | #163 | 22.10 12:00 | 22.10 18:00 | 0,0 | 2,1 | ✅ | 1 |
| 13 | [`b78feee`](https://github.com/ukma-fin-ssdm-2026/SSDM_12/actions/runs/39823938572) | #165 | 22.10 19:46 | 22.10 20:37 | 0,0 | 2,3 | ✅ | 1 |
| 14 | [`da75cf1`](https://github.com/ukma-fin-ssdm-2026/SSDM_12/actions/runs/39827162970) | #164 | 22.10 11:52 | 22.10 20:59 | 0,1 | 2,2 | ✅ | 1 |
| 15 | [`565b7de`](https://github.com/ukma-fin-ssdm-2026/SSDM_12/actions/runs/39846476437) | #162 | 22.10 00:30 | 22.10 23:13 | 0,1 | 3,6 | ✅ | 1 |
| 16 | [`6bd4e61`](https://github.com/ukma-fin-ssdm-2026/SSDM_12/actions/runs/39951245358) | #166 | 23.10 14:58 | 23.10 15:14 | 0,1 | 4,3 | ✅ | 1 |
| 17 | [`733c9c7`](https://github.com/ukma-fin-ssdm-2026/SSDM_12/actions/runs/40000314421) | #167 | 23.10 19:53 | 23.10 21:09 | 0,1 | 4,8 | ✅ | 1 |
| 18 | [`8e32210`](https://github.com/ukma-fin-ssdm-2026/SSDM_12/actions/runs/40033342527) | #171 | 23.10 21:07 | 24.10 01:25 | 0,5 | 1,2 | ⏹️ | 1 |
| 19 | [`8dcd402`](https://github.com/ukma-fin-ssdm-2026/SSDM_12/actions/runs/40033350632) | #177 | 23.10 21:49 | 24.10 01:28 | 1,6 | 3,2 | ✅ | 1 |
| 20 | [`0e780a4`](https://github.com/ukma-fin-ssdm-2026/SSDM_12/actions/runs/40039930933) | #178 | 24.10 01:13 | 24.10 08:41 | 368,8 | 3,8 | ✅ | 1 |
| 21 | [`a62a61d`](https://github.com/ukma-fin-ssdm-2026/SSDM_12/actions/runs/40121428266) | #179 | 24.10 12:04 | 24.10 21:45 | 0,1 | 10,0 | ❌ | 1 |
| 22 | [`1f3a10f`](https://github.com/ukma-fin-ssdm-2026/SSDM_12/actions/runs/40129009139) | #180 | 24.10 21:58 | 24.10 23:20 | 0,1 | 4,0 | ✅ | 1 |
| 23 | [`79f21d7`](https://github.com/ukma-fin-ssdm-2026/SSDM_12/actions/runs/40132551372) | #181 | 24.10 23:42 | 25.10 00:07 | 0,0 | 3,6 | ✅ | 1 |
| 24 | [`e9d322a`](https://github.com/ukma-fin-ssdm-2026/SSDM_12/actions/runs/40197810390) | #182 | 24.10 23:33 | 25.10 15:32 | 0,0 | 3,6 | ✅ | 1 |
| 25 | [`eae0c2a`](https://github.com/ukma-fin-ssdm-2026/SSDM_12/actions/runs/40213887363) | #184 | 25.10 16:08 | 25.10 18:57 | 0,0 | 3,5 | ✅ | 1 |
| 26 | [`4eeb1ad`](https://github.com/ukma-fin-ssdm-2026/SSDM_12/actions/runs/40216825730) | #186 | 25.10 18:02 | 25.10 19:35 | 1,0 | 3,3 | ✅ | 1 |
| 27 | [`a3ba69f`](https://github.com/ukma-fin-ssdm-2026/SSDM_12/actions/runs/40218752006) | #188 | 25.10 19:38 | 25.10 19:59 | 0,0 | 4,0 | ✅ | 1 |
| 28 | [`3d4c833`](https://github.com/ukma-fin-ssdm-2026/SSDM_12/actions/runs/40223925440) | #190 | 25.10 20:17 | 25.10 21:05 | 0,0 | 4,7 | ✅ | 1 |
| 29 | [`5f0f6c8`](https://github.com/ukma-fin-ssdm-2026/SSDM_12/actions/runs/40306059649) | #191 | 26.10 00:13 | 26.10 12:22 | 2,5 | 3,6 | ✅ | 1 |
| 30 | [`94b7444`](https://github.com/ukma-fin-ssdm-2026/SSDM_12/actions/runs/40307896144) | #198 | 26.10 12:09 | 26.10 12:33 | 0,0 | 3,8 | ✅ | 1 |
| 31 | [`a7fda3d`](https://github.com/ukma-fin-ssdm-2026/SSDM_12/actions/runs/40358646006) | #200 | 26.10 16:51 | 26.10 18:27 | 0,1 | 4,2 | ✅ | 1 |
| 32 | [`e46b6c1`](https://github.com/ukma-fin-ssdm-2026/SSDM_12/actions/runs/40360542408) | #196 | 26.10 11:40 | 26.10 18:40 | 1,1 | 3,7 | ✅ | 1 |
| 33 | [`7474881`](https://github.com/ukma-fin-ssdm-2026/SSDM_12/actions/runs/40364688090) | #197 | 26.10 12:08 | 26.10 19:05 | 0,1 | 4,2 | ✅ | 1 |
| 34 | [`107e3e2`](https://github.com/ukma-fin-ssdm-2026/SSDM_12/actions/runs/40365800955) | #202 | 26.10 18:03 | 26.10 19:12 | 0,0 | 3,7 | ✅ | 1 |
| 35 | [`870df7a`](https://github.com/ukma-fin-ssdm-2026/SSDM_12/actions/runs/40389968461) | #206 | 26.10 21:19 | 26.10 23:45 | 107,3 | 10,0 | ❌ | 1 |
| 36 | [`d849b5f`](https://github.com/ukma-fin-ssdm-2026/SSDM_12/actions/runs/40406446508) | #207 | 26.10 21:20 | 26.10 23:55 | 4,1 | 10,0 | ❌ | 1 |
| 37 | [`6a627b7`](https://github.com/ukma-fin-ssdm-2026/SSDM_12/actions/runs/40486381885) | #209 | 27.10 00:51 | 27.10 12:15 | 0,1 | 4,8 | ✅ | 1 |
| 38 | [`7fce2fa`](https://github.com/ukma-fin-ssdm-2026/SSDM_12/actions/runs/40521931175) | #210 | 27.10 15:38 | 27.10 16:41 | 0,1 | 10,2 | ✅ | 1 |
| 39 | [`fe7a841`](https://github.com/ukma-fin-ssdm-2026/SSDM_12/actions/runs/40589120728) | #212 | 27.10 21:57 | 27.10 23:47 | 1,0 | 3,4 | ✅ | 1 |
| 40 | [`580dbf8`](https://github.com/ukma-fin-ssdm-2026/SSDM_12/actions/runs/40672926847) | #213 | 28.10 00:09 | 28.10 19:38 | 0,1 | 5,3 | ✅ | 2 |
| 41 | [`4494a77`](https://github.com/ukma-fin-ssdm-2026/SSDM_12/actions/runs/40741470453) | #214 | 28.10 19:22 | 28.10 20:07 | 0,1 | 4,6 | ✅ | 1 |
| 42 | [`f1f06ae`](https://github.com/ukma-fin-ssdm-2026/SSDM_12/actions/runs/40766730778) | #215 | 28.10 22:25 | 28.10 22:53 | 0,0 | 4,1 | ✅ | 1 |
| 43 | [`ab22467`](https://github.com/ukma-fin-ssdm-2026/SSDM_12/actions/runs/40771659773) | #216 | 28.10 23:07 | 28.10 23:28 | 0,0 | 3,7 | ✅ | 1 |
| 44 | [`21e1c30`](https://github.com/ukma-fin-ssdm-2026/SSDM_12/actions/runs/40776727760) | #217 | 28.10 23:37 | 29.10 00:08 | 0,1 | 6,3 | ✅ | 1 |
| 45 | [`79e7212`](https://github.com/ukma-fin-ssdm-2026/SSDM_12/actions/runs/40872612185) | #228 | 29.10 13:36 | 29.10 14:25 | 0,1 | 4,2 | ✅ | 1 |
| 46 | [`23fca0b`](https://github.com/ukma-fin-ssdm-2026/SSDM_12/actions/runs/40901208780) | #229 | 29.10 16:01 | 29.10 17:29 | 0,1 | 4,7 | ✅ | 1 |
| 47 | [`3eaa582`](https://github.com/ukma-fin-ssdm-2026/SSDM_12/actions/runs/40920857909) | #231 | 29.10 17:53 | 29.10 19:27 | 0,1 | 3,9 | ✅ | 1 |
| 48 | [`4567041`](https://github.com/ukma-fin-ssdm-2026/SSDM_12/actions/runs/40940367993) | #230 | 29.10 17:42 | 29.10 21:31 | 0,0 | 3,6 | ✅ | 1 |
| 49 | [`883ef7a`](https://github.com/ukma-fin-ssdm-2026/SSDM_12/actions/runs/40941948739) | #232 | 29.10 19:58 | 29.10 21:45 | 2,2 | 4,1 | ✅ | 1 |
| 50 | [`9aff984`](https://github.com/ukma-fin-ssdm-2026/SSDM_12/actions/runs/40955619997) | #235 | 29.10 22:31 | 29.10 23:18 | 2,6 | 4,4 | ✅ | 1 |
| 51 | [`536bbbd`](https://github.com/ukma-fin-ssdm-2026/SSDM_12/actions/runs/40958507122) | #234 | 29.10 22:28 | 29.10 23:36 | 0,1 | 5,0 | ✅ | 1 |
| 52 | [`3276d9c`](https://github.com/ukma-fin-ssdm-2026/SSDM_12/actions/runs/41024873395) | #236 | 29.10 23:28 | 30.10 10:16 | 0,0 | 3,8 | ✅ | 1 |
| 53 | [`be350c1`](https://github.com/ukma-fin-ssdm-2026/SSDM_12/actions/runs/41064123667) | #237 | 30.10 10:49 | 30.10 15:36 | 0,0 | 3,7 | ✅ | 1 |
| 54 | [`ab15aac`](https://github.com/ukma-fin-ssdm-2026/SSDM_12/actions/runs/41127041780) | #238 | 30.10 16:47 | 30.10 23:00 | 0,0 | 4,7 | ✅ | 1 |
| 55 | [`7e384d2`](https://github.com/ukma-fin-ssdm-2026/SSDM_12/actions/runs/41127205611) | #239 | 30.10 17:15 | 30.10 23:04 | 3,5 | 4,5 | ✅ | 1 |
| 56 | [`8305b69`](https://github.com/ukma-fin-ssdm-2026/SSDM_12/actions/runs/41328893623) | #241 | 01.11 17:43 | 01.11 19:29 | 0,1 | 10,0 | ❌ | 2 |
| 57 | [`8a9a5e9`](https://github.com/ukma-fin-ssdm-2026/SSDM_12/actions/runs/41342668859) | #243 | 01.11 10:30 | 01.11 21:43 | 0,1 | 6,0 | ✅ | 1 |
| 58 | [`745ee27`](https://github.com/ukma-fin-ssdm-2026/SSDM_12/actions/runs/41349664662) | #246 | 01.11 22:31 | 01.11 23:00 | 0,1 | 0,2 | ❌ | 1 |
| 59 | [`11620ee`](https://github.com/ukma-fin-ssdm-2026/SSDM_12/actions/runs/41354651591) | #247 | 01.11 23:43 | 02.11 00:06 | 1,8 | 6,8 | ✅ | 1 |
| 60 | [`0087e4c`](https://github.com/ukma-fin-ssdm-2026/SSDM_12/actions/runs/41357096256) | #248 | 01.11 23:45 | 02.11 00:37 | 6,1 | 5,8 | ✅ | 1 |
| 61 | [`7dcd4e0`](https://github.com/ukma-fin-ssdm-2026/SSDM_12/actions/runs/41357709534) | #249 | 02.11 00:14 | 02.11 00:44 | 5,7 | 6,0 | ✅ | 1 |
| 62 | [`caf9260`](https://github.com/ukma-fin-ssdm-2026/SSDM_12/actions/runs/41366559373) | #250 | 02.11 02:05 | 02.11 02:27 | 0,1 | 7,5 | ✅ | 1 |
| 63 | [`0eb38b4`](https://github.com/ukma-fin-ssdm-2026/SSDM_12/actions/runs/41438257276) | #253 | 02.11 09:47 | 02.11 13:44 | 0,1 | 7,4 | ✅ | 1 |
| 64 | [`832106b`](https://github.com/ukma-fin-ssdm-2026/SSDM_12/actions/runs/41463470621) | #255 | 02.11 16:17 | 02.11 16:43 | 0,1 | 7,1 | ✅ | 1 |
| 65 | [`1e34eaf`](https://github.com/ukma-fin-ssdm-2026/SSDM_12/actions/runs/41472197100) | #256 | 02.11 17:11 | 02.11 17:36 | 0,1 | 6,7 | ✅ | 1 |
| 66 | [`1151841`](https://github.com/ukma-fin-ssdm-2026/SSDM_12/actions/runs/41482686673) | #257 | 02.11 18:16 | 02.11 18:42 | 0,1 | 8,4 | ✅ | 1 |
| 67 | [`74a06d3`](https://github.com/ukma-fin-ssdm-2026/SSDM_12/actions/runs/41508273407) | #258 | 02.11 19:12 | 02.11 21:22 | 0,1 | 6,5 | ✅ | 1 |
| 68 | [`a5e6a33`](https://github.com/ukma-fin-ssdm-2026/SSDM_12/actions/runs/41508404120) | #259 | 02.11 21:06 | 02.11 21:28 | 5,8 | 6,4 | ✅ | 1 |
| 69 | [`a7fb1b7`](https://github.com/ukma-fin-ssdm-2026/SSDM_12/actions/runs/41518197646) | #260 | 02.11 21:48 | 02.11 22:28 | 1,8 | 6,9 | ✅ | 1 |
| 70 | [`551f3a9`](https://github.com/ukma-fin-ssdm-2026/SSDM_12/actions/runs/41525221548) | #261 | 02.11 22:16 | 02.11 23:17 | 5,1 | 6,4 | ✅ | 1 |
| 71 | [`2f1f8ca`](https://github.com/ukma-fin-ssdm-2026/SSDM_12/actions/runs/41526217736) | #262 | 02.11 22:47 | 02.11 23:27 | 7,7 | 7,5 | ✅ | 1 |
| 72 | [`674ee82`](https://github.com/ukma-fin-ssdm-2026/SSDM_12/actions/runs/41611915703) | #263 | 03.11 00:18 | 03.11 11:44 | 0,1 | 11,2 | ✅ | 1 |
| 73 | [`83b3143`](https://github.com/ukma-fin-ssdm-2026/SSDM_12/actions/runs/41693752299) | #264 | 29.10 09:45 | 03.11 20:31 | 0,0 | 5,8 | ✅ | 1 |
| 74 | [`946e179`](https://github.com/ukma-fin-ssdm-2026/SSDM_12/actions/runs/41693831323) | #265 | 03.11 17:22 | 03.11 20:37 | 5,4 | 5,4 | ✅ | 1 |
| 75 | [`642c667`](https://github.com/ukma-fin-ssdm-2026/SSDM_12/actions/runs/41709884786) | #266 | 03.11 21:19 | 03.11 22:25 | 12,7 | 3,3 | ⏹️ | 1 |
| 76 | [`28a9509`](https://github.com/ukma-fin-ssdm-2026/SSDM_12/actions/runs/41715167472) | #267 | 03.11 22:05 | 03.11 22:51 | 0,2 | 7,9 | ✅ | 1 |
| 77 | [`638458e`](https://github.com/ukma-fin-ssdm-2026/SSDM_12/actions/runs/41722544775) | #268 | 03.11 22:52 | 03.11 23:39 | 0,1 | 8,0 | ✅ | 1 |
| 78 | [`b7a99e5`](https://github.com/ukma-fin-ssdm-2026/SSDM_12/actions/runs/41820111782) | #269 | 04.11 12:47 | 04.11 13:27 | 0,1 | 7,0 | ✅ | 1 |
| 79 | [`543515a`](https://github.com/ukma-fin-ssdm-2026/SSDM_12/actions/runs/41823102786) | #270 | 04.11 13:32 | 04.11 13:49 | 0,1 | 6,9 | ✅ | 1 |
| 80 | [`783b757`](https://github.com/ukma-fin-ssdm-2026/SSDM_12/actions/runs/42043340844) | #281 | 04.11 21:52 | 05.11 16:21 | 0,1 | 5,1 | ✅ | 1 |
| 81 | [`2d2470e`](https://github.com/ukma-fin-ssdm-2026/SSDM_12/actions/runs/42060998475) | #282 | 05.11 12:54 | 05.11 18:10 | 0,1 | 7,4 | ✅ | 1 |
| 82 | [`a44e314`](https://github.com/ukma-fin-ssdm-2026/SSDM_12/actions/runs/42119058147) | #283 | 05.11 21:05 | 06.11 00:17 | 0,1 | 8,0 | ✅ | 1 |
| 83 | [`fefa9b6`](https://github.com/ukma-fin-ssdm-2026/SSDM_12/actions/runs/42210333306) | #284 | 06.11 12:22 | 06.11 13:37 | 1,6 | 8,4 | ✅ | 1 |
| 84 | [`14dcd14`](https://github.com/ukma-fin-ssdm-2026/SSDM_12/actions/runs/42214995507) | #286 | 06.11 13:34 | 06.11 14:14 | 0,0 | 9,3 | ✅ | 1 |
| 85 | [`f7aa787`](https://github.com/ukma-fin-ssdm-2026/SSDM_12/actions/runs/42218171302) | #287 | 06.11 14:02 | 06.11 14:54 | 16,4 | 7,3 | ✅ | 1 |
| 86 | [`bed8659`](https://github.com/ukma-fin-ssdm-2026/SSDM_12/actions/runs/42228534948) | #290 | 06.11 15:05 | 06.11 15:54 | 3,6 | 1,6 | ❌ | 1 |
| 87 | [`20e2873`](https://github.com/ukma-fin-ssdm-2026/SSDM_12/actions/runs/42233893740) | #288 | 06.11 14:16 | 06.11 17:47 | 75,0 | 6,6 | ✅ | 1 |
| 88 | [`50d402d`](https://github.com/ukma-fin-ssdm-2026/SSDM_12/actions/runs/42248615755) | #291 | 06.11 16:29 | 06.11 18:09 | 0,1 | 6,8 | ✅ | 1 |
| 89 | [`6c77287`](https://github.com/ukma-fin-ssdm-2026/SSDM_12/actions/runs/42375248329) | #293 | 07.11 14:42 | 07.11 15:10 | 0,1 | 6,2 | ✅ | 1 |
| 90 | [`2939ff7`](https://github.com/ukma-fin-ssdm-2026/SSDM_12/actions/runs/42375820485) | #292 | 06.11 21:15 | 07.11 15:18 | 0,0 | 6,7 | ✅ | 1 |
| 91 | [`320038f`](https://github.com/ukma-fin-ssdm-2026/SSDM_12/actions/runs/42401975687) | #295 | 07.11 16:35 | 07.11 20:42 | 0,0 | 8,2 | ✅ | 1 |
| 92 | [`0390807`](https://github.com/ukma-fin-ssdm-2026/SSDM_12/actions/runs/42504815757) | #294 | 07.11 15:25 | 08.11 19:31 | 0,0 | 6,9 | ✅ | 1 |
| 93 | [`90936a1`](https://github.com/ukma-fin-ssdm-2026/SSDM_12/actions/runs/42510364482) | #298 | 08.11 13:22 | 08.11 20:39 | 2,6 | 6,6 | ✅ | 1 |
| 94 | [`82c2bd0`](https://github.com/ukma-fin-ssdm-2026/SSDM_12/actions/runs/42514198771) | #296 | 08.11 12:48 | 08.11 21:25 | 2,6 | 6,5 | ✅ | 1 |
| 95 | [`509b5ef`](https://github.com/ukma-fin-ssdm-2026/SSDM_12/actions/runs/42516240902) | #297 | 08.11 18:20 | 08.11 21:47 | 0,1 | 6,7 | ✅ | 1 |
| 96 | [`4dd3410`](https://github.com/ukma-fin-ssdm-2026/SSDM_12/actions/runs/42523613037) | #301 | 08.11 22:15 | 08.11 23:16 | 0,0 | 8,5 | ✅ | 1 |
| 97 | [`4b2df3a`](https://github.com/ukma-fin-ssdm-2026/SSDM_12/actions/runs/42528340612) | #302 | 08.11 23:46 | 09.11 00:12 | 0,0 | 7,9 | ✅ | 1 |
| 98 | [`cac0fa5`](https://github.com/ukma-fin-ssdm-2026/SSDM_12/actions/runs/42528892863) | #303 | 08.11 23:50 | 09.11 00:20 | 1,8 | 8,1 | ✅ | 1 |
| 99 | [`82aacea`](https://github.com/ukma-fin-ssdm-2026/SSDM_12/actions/runs/42532371209) | #305 | 09.11 00:16 | 09.11 01:06 | 2,3 | 12,1 | ✅ | 1 |
| 100 | [`cc8d363`](https://github.com/ukma-fin-ssdm-2026/SSDM_12/actions/runs/42532661541) | #307 | 09.11 00:21 | 09.11 01:19 | 10,7 | 13,2 | ✅ | 1 |
| 101 | [`926b269`](https://github.com/ukma-fin-ssdm-2026/SSDM_12/actions/runs/42533406610) | #309 | 09.11 00:32 | 09.11 01:29 | 14,9 | 10,0 | ✅ | 1 |
| 102 | [`eaf6bcc`](https://github.com/ukma-fin-ssdm-2026/SSDM_12/actions/runs/42533716220) | #308 | 09.11 00:24 | 09.11 01:38 | 21,4 | 8,7 | ✅ | 1 |
| 103 | [`62ac45f`](https://github.com/ukma-fin-ssdm-2026/SSDM_12/actions/runs/42533867636) | #304 | 09.11 00:05 | 09.11 02:10 | 35,5 | 24,8 | ✅ | 1 |
| 104 | [`b950941`](https://github.com/ukma-fin-ssdm-2026/SSDM_12/actions/runs/42537157036) | #313 | 09.11 01:09 | 09.11 02:18 | 19,4 | 7,6 | ✅ | 1 |

## Як відтворити

```bash
python scripts/dora_metrics.py --since 2026-10-19 --until 2026-11-09 --repo ukma-fin-ssdm-2026/SSDM_12 --branch main --event push --workflow CI --transport gh --dataset docs/ci-cd/evidence/dora-dataset.json --out docs/ci-cd/dora-auto.md --json docs/ci-cd/dora-auto.json
```
