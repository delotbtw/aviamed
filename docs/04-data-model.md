# 04. Модель данных

*Черновик v0.1, 26.10.2026. СУБД: PostgreSQL. Все таблицы имеют `id`, `created_at`, `updated_at`, если не указано иное.*

## 1. Пользователи

**users**
| Поле | Описание |
|---|---|
| id | Первичный ключ |
| email | Уникальный, логин |
| password_hash | Хэш пароля |
| role | admin / registrar / doctor / athlete / coach |
| last_name, first_name, middle_name | ФИО |
| phone | Телефон |
| is_active | Признак активности |
| last_login_at | Время последнего входа |

**athlete_profiles** (1:1 с users)
| Поле | Описание |
|---|---|
| user_id | PK, FK users |
| birth_date, sex | Дата рождения, пол |
| faculty, study_group | Факультет, группа |
| sport_id | FK sports |
| training_stage | Этап подготовки (enum) |
| registry_number | Реестровый номер спортсмена (при наличии) |
| health_group | Группа здоровья I–IV, может быть пустой |
| coach_id | FK users (тренер) |

**coach_profiles** (1:1 с users): `user_id`, `sport_id`.

**doctor_profiles** (1:1 с users): `user_id`, `specialty_id`, `cabinet`, `can_issue_conclusion` (bool; только врач по спортивной медицине).

**staff_profiles** (необязательно, для регистратуры и админа): `user_id`, должность, рабочее место.

## 2. Справочники (фиксированные)

| Таблица | Поля |
|---|---|
| sports | id, название |
| specialties | id, название |
| exam_types | id, code, название, specialty_id (может быть пустым), вид (приём / лаборатория / функциональная диагностика / нагрузочный тест) |
| exam_programs | id, название (base / umo), срок действия в месяцах |
| exam_program_items | program_id, exam_type_id, is_required |

Наполнение справочников — в [06-exam-programs.md](06-exam-programs.md).

## 3. Процесс

**medical_cases** (дело на обследование)
| Поле | Описание |
|---|---|
| athlete_id | FK users |
| program_id | FK exam_programs |
| status | Статус (см. 05) |
| opened_by | Кто открыл |
| opened_at, closed_at | Даты |
| valid_until | Срок действия результата |
| version | Версия для защиты от одновременных правок |

**examinations** (осмотр)
| Поле | Описание |
|---|---|
| case_id | FK medical_cases |
| exam_type_id | FK exam_types |
| doctor_id | FK users |
| appointment_id | FK appointments |
| status | pending / done |
| result | норма / отклонение / противопоказание |
| findings | Текст заключения врача по осмотру |
| performed_at | Когда проведён |

**stress_tests** (1:1 с examination)
| Поле | Описание |
|---|---|
| protocol | Тип пробы (enum) |
| hr_rest, hr_peak | ЧСС в покое, на пике |
| hr_rec_1m, hr_rec_3m | ЧСС через 1 и 3 минуты восстановления |
| bp_before, bp_after | АД до и после |
| spo2_min | Минимальный SpO₂ |
| power_w, duration_s | Мощность, длительность |
| pwc170 | Показатель PWC170 |
| borg_score | Субъективная нагрузка по шкале Борга |
| ecg_note | Заключение по ЭКГ |
| vo2max | Только при газоанализе |

**conclusions** (1:1 с medical_cases)
| Поле | Описание |
|---|---|
| number | Реестровый номер медицинского заключения |
| case_id | Уникальный, FK |
| doctor_id | Кто выдал (врач по спортивной медицине); должность берётся из его профиля |
| decision | допущен / не допущен / повторный осмотр |
| admitted_training, admitted_competitions, admitted_physical_events, admitted_gto | К чему допущен (да/нет по каждому пункту формы) |
| event_name, sport_discipline | Название мероприятия, спортивная дисциплина (при наличии) |
| has_restrictions, restrictions_term, restrictions | Ограничения, в том числе нагрузок: да/нет, срок, описание |
| issued_at, valid_until | Дата выдачи, действительно до (не более года) |

Поля соответствуют форме медицинского заключения (приложение 2 к приказу 484н) и используются при генерации PDF. Реквизиты медицинской организации (наименование, адрес, ОГРН) для шапки хранятся в настройках приложения.

## 4. Расписание

**slots**: `doctor_id`, `start_at`, `end_at`, `status` (free / booked / closed). Уникальность пары (doctor_id, start_at).

**appointments**: `slot_id` (уникальный), `athlete_id`, `case_id`, `status`, `created_by`, `created_at`, `cancelled_at`.

Уникальность `slot_id` в appointments гарантирует на уровне БД, что на один слот записан один человек, даже при одновременных запросах.

## 5. Согласия

**consents**: `user_id`, тип согласия, **номер бумажного согласия** (оригинал хранится в медцентре), дата подписания, дата отзыва (если был).

В системе мы храним только номер и дату, сканы не загружаем. Оригинал остаётся у оператора (медцентра).

## 6. Служебные таблицы

| Таблица | Поля |
|---|---|
| status_history | entity_type, entity_id, from_status, to_status, changed_by, changed_at, comment |
| audit_log | user_id, action, entity_type, entity_id, ip, created_at |
| refresh_tokens | user_id, token_hash, expires_at, revoked_at, user_agent |

## 7. Ограничения целостности

- Перечисления (роль, статусы, решение) оформляем типом Enum и проверкой на уровне БД.
- Внешние ключи с явным поведением при удалении; пользователей не удаляем физически, а деактивируем.
- Один активный (не завершённый и не отменённый) дело на спортсмена по одной программе.
- Одно заключение на дело.
- Индексы: по `athlete_id`, `status`, `doctor_id`, `start_at`.
- `created_by` / `updated_by` в бизнес-таблицах для отслеживания авторства.

## 8. Миграции

Версионирование схемы через Alembic. Любое изменение схемы — только через миграцию.
