# Остаточна локальна звірка 44 FR — 01.11.2026

Перевірено локальну feature/midterm-admin-availability на базі ce1c58a.
У requirements.md є рівно **44 окремі FR**: пропуски між діапазонами ID не є
відсутніми вимогами. Для кожної нижче прочитано реалізацію та конкретні assert
тестів; мітка pytest.mark.req сама по собі не зараховувалась як доказ.
Посилання на символи додатково перевірені AST, а кожен наведений тест — за
фактичним JUnit цього прогону.

**Результат:** 44/44 мають реалізацію і позитивні/негативні докази в локальній
системі в межах чинних API-контрактів і C-002. Повний pytest: **684 passed**,
146,66 с, api + unislot з гілками **98,29%**, без skipped/failed/error.
Це висновок про локальний код; він не змінює оцінку викладача, стан main,
галочки прийняття user stories чи статус командних ADR/OQ. Push/PR/CI не виконані.

## Підсумок за функціями

| Функція | FR | Локальний результат |
|---|---:|---|
| F1: автентифікація й авторизація | 7 | Реалізовані та перевірені |
| F2: доступність, шаблони, календар | 6 | Реалізовані та перевірені |
| F3: пошук | 4 | Реалізовані та перевірені |
| F4: бронювання | 7 | Реалізовані та перевірені |
| F5: скасування та перенесення | 6 | Реалізовані та перевірені |
| F6: сповіщення | 5 | Реалізовані з локальним адаптером C-002 та Worker |
| F7: адміністрування й аудит | 9 | Реалізовані та перевірені |

## Реалізація та вибрані докази

У всіх рядках статус — «підтверджено локально». У стовпці тестів наведено
основні докази; це не весь набір перевірок відповідної функції. API-тести
контракту доповнюються PostgreSQL-тестами, живим HTTP-сценарієм і окремими
навантажувальними прогонами; memory-тест не називається доказом SQL-конкурентності.

### F1

| FR | Поведінка | Код | Перевірка |
|---|---|---|---|
| FR-001 | Самореєстрація студента | [auth_service.py: register](../../src/api/services/auth_service.py) | [test_registration_never_accepts_privileges_from_client](../../tests/api/test_password_auth.py)<br>[test_registration_is_atomic_when_database_rejects_credentials](../../tests/integration/test_persisted_auth.py) |
| FR-002 | Ігнорування переданої ролі | [auth_service.py: register](../../src/api/services/auth_service.py) | [test_registration_never_accepts_privileges_from_client](../../tests/api/test_password_auth.py) |
| FR-003 | Унікальна пошта без регістру | [auth_service.py: register](../../src/api/services/auth_service.py) | [test_email_uniqueness_ignores_case_and_spaces](../../tests/api/test_password_auth.py)<br>[test_parallel_case_variant_registration_creates_one_account](../../tests/integration/test_persisted_auth.py) |
| FR-004 | Argon2id та повний пароль | [passwords.py: hash_password](../../src/api/infrastructure/passwords.py) | [test_full_password_is_preserved_without_72_byte_truncation](../../tests/api/test_password_auth.py)<br>[test_password_and_session_survive_reopening_database](../../tests/integration/test_persisted_auth.py) |
| FR-005 | Однакова помилка входу | [auth_service.py: login](../../src/api/services/auth_service.py) | [test_login_error_does_not_disclose_account_existence](../../tests/api/test_password_auth.py) |
| FR-006 | Обмеження невдалих входів | [auth_service.py: login](../../src/api/services/auth_service.py) | [test_throttle_applies_equally_to_known_and_unknown_and_does_not_extend](../../tests/api/test_password_auth.py)<br>[test_failed_login_commits_user_counter_and_unknown_account_counter](../../tests/integration/test_persisted_auth.py) |
| FR-007 | Три ролі та відмова у чужих операціях | [security.py: get_current_user](../../src/api/security.py)<br>[security.py: require_roles](../../src/api/security.py) | [test_rbac_decision_table](../../tests/api/test_rbac_decision_table.py)<br>[test_decision_table_covers_every_protected_operation_for_every_role](../../tests/api/test_rbac_decision_table.py)<br>[test_role_revocation_and_account_disable_affect_existing_session](../../tests/integration/test_persisted_auth.py) |

### F2

| FR | Поведінка | Код | Перевірка |
|---|---|---|---|
| FR-010 | Разові слоти власного ресурсу | [slot_service.py: create_slot](../../src/api/stubs/slot_service.py) | [test_provider_publishes_slot_on_own_resource](../../tests/api/test_slots.py)<br>[test_duration_and_time_validation](../../tests/api/test_slots.py) |
| FR-011 | Відхилення перетинів слотів | [slot_service.py: create_slot](../../src/api/stubs/slot_service.py) | [test_overlap_rejected_adjacent_allowed](../../tests/api/test_slots.py)<br>[test_slot_exclusion_and_inactive_history](../../tests/integration/test_persistence.py) |
| FR-012 | Щотижневий шаблон і горизонт | [template_service.py: save_template](../../src/api/stubs/template_service.py)<br>[worker_service.py: refresh_horizon](../../src/api/services/worker_service.py) | [test_template_materializes_entire_horizon_and_is_searchable](../../tests/api/test_availability_templates.py)<br>[test_horizon_extends_without_a_browser_and_refresh_is_idempotent](../../tests/integration/test_worker_operations.py) |
| FR-013 | Блокування власного часу | [availability_service.py: create_block](../../src/api/stubs/availability_service.py) | [test_overlapping_blocks_keep_time_unavailable_until_both_are_removed](../../tests/api/test_availability_blocks.py) |
| FR-014 | Скасування через блокування з причиною | [availability_service.py: create_block](../../src/api/stubs/availability_service.py)<br>[notification_service.py: booking_cancelled](../../src/api/stubs/notification_service.py) | [test_block_cancels_all_overlapping_future_bookings](../../tests/api/test_availability_blocks.py)<br>[test_provider_block_delivers_reason_to_student_even_if_gateway_is_down](../../tests/integration/test_outbox.py) |
| FR-015 | Календар і завантаження провайдера | [workspace.py: resource_calendar](../../src/api/routers/workspace.py) | [test_calendar_has_whole_range_totals_and_page_without_student_data](../../tests/api/test_calendar_audit.py) |

### F3

| FR | Поведінка | Код | Перевірка |
|---|---|---|---|
| FR-020 | Вільні слоти у горизонті | [queries.py: search_slots](../../src/api/infrastructure/queries.py)<br>[slot_service.py: is_free](../../src/api/stubs/slot_service.py) | [test_search_returns_only_free_slots_in_time_order](../../tests/api/test_slots.py)<br>[test_date_outside_horizon_is_rejected](../../tests/api/test_slots.py)<br>[test_sql_search_matches_memory_filters_and_cursor](../../tests/integration/test_sql_paths.py) |
| FR-021 | Фільтри провайдера, типу й дати | [queries.py: search_slots](../../src/api/infrastructure/queries.py) | [test_filters_combine](../../tests/api/test_slots.py)<br>[test_cached_search_shape_keeps_filter_values_and_current_rows_fresh](../../tests/integration/test_sql_paths.py) |
| FR-022 | Мінімальна місткість лише аудиторій | [queries.py: _search_query](../../src/api/infrastructure/queries.py)<br>[slot_service.py: _matches_filters](../../src/api/stubs/slot_service.py) | [test_min_capacity_applies_to_rooms_only](../../tests/api/test_slots.py)<br>[test_sql_search_matches_memory_filters_and_cursor](../../tests/integration/test_sql_paths.py) |
| FR-023 | Приховування зайнятих, заблокованих і початих | [queries.py: _search_query](../../src/api/infrastructure/queries.py)<br>[slot_service.py: is_free](../../src/api/stubs/slot_service.py) | [test_search_returns_only_free_slots_in_time_order](../../tests/api/test_slots.py)<br>[test_booked_slot_disappears_from_search](../../tests/api/test_slots.py) |

### F4

| FR | Поведінка | Код | Перевірка |
|---|---|---|---|
| FR-030 | Бронювання у горизонті | [booking_commands.py: create_booking](../../src/api/infrastructure/booking_commands.py)<br>[rules.py: ensure_slot_bookable](../../src/unislot/booking/domain/rules.py) | [test_booking_a_free_slot](../../tests/api/test_bookings.py)<br>[test_booking_and_outbox_survive_adapter_restart](../../tests/integration/test_persistence.py) |
| FR-031 | Негайно активне бронювання | [booking_commands.py: create_booking](../../src/api/infrastructure/booking_commands.py)<br>[booking_service.py: _new_booking](../../src/api/stubs/booking_service.py) | [test_booking_a_free_slot](../../tests/api/test_bookings.py) |
| FR-032 | Один переможець за конкуренції | [booking_commands.py: create_booking](../../src/api/infrastructure/booking_commands.py) | [test_parallel_independent_connections_have_one_booking_winner](../../tests/integration/test_persistence.py) |
| FR-033 | Ліміт із поясненням значення | [rules.py: ensure_within_student_limits](../../src/unislot/booking/domain/rules.py)<br>[booking_commands.py: create_booking](../../src/api/infrastructure/booking_commands.py) | [test_limit_reached_names_limit_and_count](../../tests/api/test_bookings.py)<br>[test_parallel_student_limit_is_preserved](../../tests/integration/test_sql_paths.py) |
| FR-034 | Закриття запису від початку слота | [rules.py: ensure_slot_bookable](../../src/unislot/booking/domain/rules.py) | [test_unbookable_slots_give_409_with_reason](../../tests/api/test_bookings.py)<br>[test_sql_booking_preserves_domain_rejections](../../tests/integration/test_sql_paths.py) |
| FR-035 | Заборона перетину записів одного студента | [rules.py: ensure_within_student_limits](../../src/unislot/booking/domain/rules.py) | [test_unbookable_slots_give_409_with_reason](../../tests/api/test_bookings.py)<br>[test_sql_booking_preserves_domain_rejections](../../tests/integration/test_sql_paths.py) |
| FR-036 | Власні активні та минулі бронювання | [booking_service.py: list_mine](../../src/api/stubs/booking_service.py) | [test_my_bookings_active_first](../../tests/api/test_bookings.py)<br>[test_my_bookings_filter_and_empty_result](../../tests/api/test_bookings.py)<br>[test_separate_api_and_worker_processes_share_durable_state](../../tests/integration/test_persistence.py) |

### F5

| FR | Поведінка | Код | Перевірка |
|---|---|---|---|
| FR-040 | Скасування в межах вікна | [booking_service.py: cancel](../../src/api/stubs/booking_service.py)<br>[rules.py: ensure_changeable](../../src/unislot/booking/domain/rules.py) | [test_cancel_exactly_at_deadline_is_allowed](../../tests/api/test_bookings.py)<br>[test_cancel_after_deadline_names_the_deadline](../../tests/api/test_bookings.py) |
| FR-041 | Фіксований дедлайн у підтвердженні | [booking_commands.py: _response](../../src/api/infrastructure/booking_commands.py)<br>[rules.py: cancel_deadline](../../src/unislot/booking/domain/rules.py) | [test_booking_a_free_slot](../../tests/api/test_bookings.py)<br>[test_policy_versions_keep_existing_bookings_unchanged](../../tests/api/test_admin_management.py) |
| FR-042 | Звільнення слота після скасування | [booking_service.py: cancel](../../src/api/stubs/booking_service.py) | [test_cancel_frees_the_slot](../../tests/api/test_bookings.py) |
| FR-043 | Атомарне перенесення | [booking_service.py: reschedule](../../src/api/stubs/booking_service.py) | [test_reschedule_is_atomic_replacement](../../tests/api/test_bookings.py)<br>[test_failed_reschedule_keeps_notice_success_replaces_it](../../tests/integration/test_outbox.py) |
| FR-044 | Вікно перенесення і виняток із ліміту | [booking_service.py: reschedule](../../src/api/stubs/booking_service.py)<br>[rules.py: ensure_within_student_limits](../../src/unislot/booking/domain/rules.py) | [test_reschedule_at_limit_is_allowed](../../tests/api/test_bookings.py)<br>[test_reschedule_after_deadline_or_to_same_slot](../../tests/api/test_bookings.py) |
| FR-045 | Після початку зміни заборонені всім ролям | [rules.py: ensure_changeable](../../src/unislot/booking/domain/rules.py)<br>[availability_service.py: create_block](../../src/api/stubs/availability_service.py) | [test_started_slot_cannot_be_changed_even_before_deadline_check](../../tests/unit/test_booking_rules.py)<br>[test_started_booking_rejects_entire_block_without_partial_cancellation](../../tests/api/test_availability_blocks.py) |

### F6

| FR | Поведінка | Код | Перевірка |
|---|---|---|---|
| FR-050 | Підтвердження студенту | [notification_service.py: booking_created](../../src/api/stubs/notification_service.py)<br>[outbox.py: dispatch_due](../../src/api/infrastructure/outbox.py) | [test_confirmation_and_provider_delivery_are_private_and_idempotent](../../tests/integration/test_outbox.py) |
| FR-051 | Нагадування за 24 години | [reminders.py: reminder_due_at](../../src/unislot/notifications/domain/reminders.py)<br>[outbox.py: dispatch_due](../../src/api/infrastructure/outbox.py) | [test_booking_exactly_24_hours_ahead_still_gets_a_reminder](../../tests/unit/test_reminders.py)<br>[test_lead_is_absolute_time_across_the_dst_change](../../tests/unit/test_reminders.py)<br>[test_reminder_is_delayed_until_due](../../tests/integration/test_outbox.py) |
| FR-052 | Провайдеру про створення й скасування | [notification_service.py: booking_created](../../src/api/stubs/notification_service.py)<br>[notification_service.py: booking_cancelled](../../src/api/stubs/notification_service.py) | [test_confirmation_and_provider_delivery_are_private_and_idempotent](../../tests/integration/test_outbox.py)<br>[test_cancellation_after_claim_prevents_late_worker_delivery](../../tests/integration/test_outbox.py) |
| FR-053 | Стійка черга повторів без блокування броні | [outbox.py: dispatch_due](../../src/api/infrastructure/outbox.py) | [test_failure_never_blocks_booking_and_survives_retry](../../tests/integration/test_outbox.py)<br>[test_crash_between_send_and_ack_retries_without_duplicate_delivery](../../tests/integration/test_outbox.py)<br>[test_operator_lists_minimal_fields_and_retries_one_failed_message](../../tests/integration/test_worker_operations.py) |
| FR-054 | Перепланування після перенесення | [booking_service.py: reschedule](../../src/api/stubs/booking_service.py)<br>[notification_service.py: booking_cancelled](../../src/api/stubs/notification_service.py) | [test_failed_reschedule_keeps_notice_success_replaces_it](../../tests/integration/test_outbox.py) |

### F7

| FR | Поведінка | Код | Перевірка |
|---|---|---|---|
| FR-060 | Створення й редагування ресурсів | [resource_service.py: create_resource](../../src/api/stubs/resource_service.py)<br>[resource_service.py: update_resource](../../src/api/stubs/resource_service.py) | [test_admin_creates_room_with_location_and_audit](../../tests/api/test_resources.py)<br>[test_patch_changes_only_sent_fields](../../tests/api/test_resources.py) |
| FR-061 | Призначення провайдера ресурсу | [resource_service.py: _check_provider](../../src/api/stubs/resource_service.py)<br>[resource_service.py: update_resource](../../src/api/stubs/resource_service.py) | [test_admin_creates_room_with_location_and_audit](../../tests/api/test_resources.py)<br>[test_provider_must_have_provider_role](../../tests/api/test_resources.py)<br>[test_provider_role_requires_reassignment_of_owned_resources](../../tests/api/test_admin_management.py) |
| FR-062 | Надання й відкликання ролей | [admin_service.py: change_role](../../src/api/stubs/admin_service.py) | [test_role_changes_take_effect_on_the_next_request](../../tests/api/test_admin_management.py)<br>[test_role_put_and_delete_are_idempotent](../../tests/api/test_admin_management.py) |
| FR-063 | Захист останнього адміністратора | [admin_service.py: change_role](../../src/api/stubs/admin_service.py)<br>[rules.py: ensure_role_revocable](../../src/unislot/admin/domain/rules.py) | [test_last_admin_is_protected_without_mutation](../../tests/api/test_admin_management.py)<br>[test_concurrent_self_revocation_always_keeps_one_admin](../../tests/api/test_admin_management.py) |
| FR-064 | Зміна ліміту й вікна | [admin_service.py: update_policy](../../src/api/stubs/admin_service.py) | [test_policy_versions_keep_existing_bookings_unchanged](../../tests/api/test_admin_management.py)<br>[test_bad_policy_is_422_and_does_not_change_state](../../tests/api/test_admin_management.py) |
| FR-065 | Стара бронь зберігає свою політику | [admin_service.py: update_policy](../../src/api/stubs/admin_service.py)<br>[booking_commands.py: create_booking](../../src/api/infrastructure/booking_commands.py) | [test_policy_versions_keep_existing_bookings_unchanged](../../tests/api/test_admin_management.py)<br>[test_lowering_limit_preserves_bookings_and_blocks_new_ones](../../tests/api/test_admin_management.py)<br>[test_old_cancel_window_still_applies_after_policy_change](../../tests/api/test_admin_management.py) |
| FR-066 | Аудит ресурсу, ролей і політики | [admin_service.py: _audit](../../src/api/stubs/admin_service.py)<br>[resource_service.py: _audit](../../src/api/stubs/resource_service.py) | [test_admin_creates_room_with_location_and_audit](../../tests/api/test_resources.py)<br>[test_role_put_and_delete_are_idempotent](../../tests/api/test_admin_management.py)<br>[test_policy_versions_keep_existing_bookings_unchanged](../../tests/api/test_admin_management.py)<br>[test_audit_failure_rolls_back_admin_change](../../tests/integration/test_persistence.py) |
| FR-067 | Append-only аудит | [security.py: install_audit_protection](../../src/api/infrastructure/security.py)<br>[security.py: grant_runtime](../../src/api/infrastructure/security.py) | [test_runtime_cannot_change_audit](../../tests/integration/test_persistence.py)<br>[test_owner_triggers_also_reject_audit_mutation](../../tests/integration/test_persistence.py) |
| FR-068 | Читання аудиту з фільтрами | [workspace.py: audit_log](../../src/api/routers/workspace.py) | [test_audit_filter_pagination_before_after_and_read_only](../../tests/api/test_calendar_audit.py)<br>[test_audit_never_exposes_nested_auth_secrets](../../tests/api/test_calendar_audit.py) |

## Межі висновку та незавершені погодження

- **FR-001:** Володіння поштою не підтверджується: C-002, а не відсутня реалізація FR-001.
- **FR-006:** Працює 5 спроб / 300 с; командне рішення OQ-001 ще не зафіксоване.
- **FR-012:** Для автоматичного подовження потрібен запущений Worker; DST-переходи перевірені окремо.
- **FR-015:** Додано на запит Дениса; історичне OQ-004 потребує командного погодження. Період до 31 дня, списки з пагінацією.
- **FR-032:** Додатково 3 навантажувальні прогони на PostgreSQL: кожного разу 1×201 + 99×409; посилання нижче.
- **FR-050:** Outbox створюється разом із бронею; Worker доставляє у постійну особисту скриньку. Локальний адаптер за C-002, без SMTP/SMS.
- **FR-051:** Час доставки перевірено контрольованим clock; реальні 24 години під час свіжого запуску не очікували. Потрібен Worker.
- **FR-052:** Постійна скринька C-002; доставка окремим Worker також перевірена живим HTTP-сценарієм.
- **FR-053:** Після вичерпання спроб status=failed; явний операторський повтор із причиною та аудитом.
- **FR-060:** Тип є полем створення; його зміна PATCH навмисно заборонена чинним контрактом. Назва/місткість/провайдер редагуються.
- **FR-067:** Runtime не має UPDATE/DELETE/TRUNCATE/DDL; тригери захищають журнал. DB superuser, який змінює сам механізм захисту, не є роллю продукту.
- **FR-068:** Admin-only; дата, автор і дія, період до 31 дня, пагінація. Включено на запит Дениса; OQ-004 очікує командного PR.

Додаткові узгодження: OQ-002 про домен пошти, OQ-003 про політику паролів,
AQ-06/DD-06 про параметри сесій та DD-15 про вибір UI не оголошуються
ухваленими від імені команди. Реалізація вже має робочі значення, але технічний
тест не замінює командне рішення. UI/API/Worker працюють на синтетичних даних C-003.

FR-032 додатково підтверджено трьома реальними HTTP-гоночними прогонами по
100 запитів на один слот: 1×201, 99×409, у БД одна confirmed.
Методика і сирі агрегати — у [завершенні продуктивності](performance-completion.md).
Дедлайни, межі 24 годин та DST перевірялися контрольованим часом у тестах;
це окремо від живого запуску, де нагадування очікує майбутнього scheduled_for.

## Відтворення запуску

Свіжа копія tracked-джерел без .env, venv і pgdata; новий venv та встановлення
requirements-dev.txt; local-init створює нову власну БД, migrate повторюється
без скидання даних. Профіль: Windows 10 22H2, Python 3.13.13, PostgreSQL 16,
два процеси Uvicorn, interval 1 мс, demoBearer=0, окремий Worker.
Використовувалася та сама фізична машина Дениса. Мережевий сценарій ішов через
реальні HTTP/cookie/CSRF; новий браузерний DOM-огляд у цьому прогоні не заявляється.
HTML, JS MIME, CSP та Swagger endpoints перевірені HTTP-запитами.

Після корекцій harness пройшли **три послідовні повні HTTP-сценарії**, кожен на
новій власній БД; нове venv, встановлене під час початкового запуску, використане
повторно. У кожному: 0005, два живі server PID, окремий Worker, реєстрація з
відхиленням підвищення ролі, бронювання та повтор ключа, негативне й успішне
перенесення, звільнення слота після скасування, особисті скриньки, календар,
фільтрований аудит, перезапуск API зі збереженою історією й сесією, logout,
notification CLI та pip check. Два застарілі нагадування мають cancelled;
нагадування іншого чинного бронювання лишається pending. Це перевірка стану
черги, а не твердження про негайну доставку майбутнього нагадування.

Порядок та критерії перевірки на іншому ПК — у
[native-launch-checklist.md](native-launch-checklist.md).
Запуск на іншому фізичному ПК залишається **не підтвердженим** до отримання
результату саме з нього. Зміна каталогу або новий venv на цьому ПК не є цією перевіркою.
Python 3.12 та Linux/macOS тут не перевірялися; цей звіт не підтверджує PORT-001 і не є
перевіркою публічного Render-хостингу. PERF-001 тепер оцінюється за нативним профілем.
Матеріали Лаб8 не змінені.

## Знайдені неточності

Виправлено лише застарілі модульні docstrings сервісів у src/api/stubs/:
вони називали все memory-прототипом, хоча StoreProxy вже під'єднує PostgreSQL.
Назви пакета та імпорти збережено; змін у бізнес-логіці, DDL, API, залежностях
і порогах немає. Історичні звіти лабораторних не переписувалися заднім числом.

У зовнішньому перевірочному сценарії виправлені адреса /health і спосіб
визначення двох Uvicorn-процесів: Windows venv може мати проміжний launcher,
тому одного ParentProcessId недостатньо. Це помилки harness, не падіння pytest.
Окремий запуск отримав ReadTimeout; його лог збережено, причина не встановлена.
Результати повторів наведені в JSON, цей таймаут не видається за виправлену
помилку продукту або за доказ відсутності всіх можливих мережевих збоїв.

## Докази та використання ШІ

Стислі результати — у [validation/fr-launch-audit-2026-11-01.json](validation/fr-launch-audit-2026-11-01.json).
Повні JUnit, coverage, fr-evidence.json, traceability.json, журнали встановлення,
API/Worker, невдалі спроби та fresh-launch*.json зберігаються поза Git:
Midterm_features_2026-11-01/fr-launch-audit. Файли з URL/паролями не публікуються;
тимчасові процеси зупиняються, створені тестові pgdata та env видаляються.

Codex виконав локальну звірку коду, assert і журналів, автоматичні прогони,
виправлення docstrings та підготував ці документи. Ручна перевірка чи схвалення
інших учасників, інший комп'ютер і новий GitHub CI не приписуються.
