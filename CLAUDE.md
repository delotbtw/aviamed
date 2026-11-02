# Project: АвиаМед (медицинский центр МАИ)
**Цель и метрика для жюри**: веб-система допуска студентов-спортсменов: запись, осмотры, заключение (PDF), роли и аудит; метрика — работающий сквозной процесс и отсутствие гонок данных.
**Класс задачи**: проверяется тестами (TDD: спека → красные тесты → реализация → ревью).
**Демо-сценарий**: регистратура заводит спортсмена и открывает дело → спортсмен записывается на слот → приход → врач вносит результаты → спортврач выдаёт заключение → PDF.

## Стек и команды
- Backend: FastAPI (async), SQLAlchemy 2.x async, Alembic | Frontend: Jinja2 + HTMX + Alpine.js, тема Hallmark/Almanac | DB: PostgreSQL 17, Redis (лимиты, токены), nginx, Docker Compose
- Запуск: `make up` (http://localhost; демо-данные `make seed CONFIRM=local`, пароль демо `Demo12345!`) | целевой тест: `uv run pytest tests/<модуль> -q --tb=short` (БД: `make test-db`) | полная проверка: `make test` + `make lint` + `alembic check`
- Параллельные прогоны тестов — у каждого агента СВОЯ БД: `TEST_DATABASE_URL=postgresql+asyncpg://medcenter:medcenter@localhost:55432/medcenter_test_<имя>` (см. tests/README.md)

## Структура и образцы (для lite-агентов)
- Каталоги: `app/<модуль>/` (router, service(s), schemas), `app/models/`, `app/repositories/`, `app/core/` (инфраструктура, не импортирует фичи), `app/composition.py` (DI-сборка), `app/web/` + `app/templates/` (страницы), `migrations/versions/`, `docs/` (+ `docs/stages/` — спеки этапов), `tests/`
- Образцы: модель `app/models/schedule.py` | схема `app/schedule/schemas.py` | роутер `app/schedule/router.py` | шаблон `app/templates/cabinet/slots.html` | тест `tests/schedule/test_booking.py`; сервис с блокировками `app/schedule/booking.py`

## Конвенции (не повторять в спеках)
1. Ошибки: доменные исключения (`app/core/exceptions.py`) → HTTP в одном месте (`app/core/errors.py`), JSON `{"detail": ...}`; схема БД только через Alembic-миграции
2. Слои: роутер (тонкий) → сервис (бизнес-логика, без HTTP/SQLAlchemy) → репозиторий (только запросы); DI через конструктор и `app/composition.py`; UnitOfWork, не `AsyncSession` в сервисах; `tests/test_architecture.py` стережёт границы
3. Конкурентность: только блокировки строк и ограничения БД (`FOR NO KEY UPDATE`, unique/exclusion), без `LOCK TABLE`/SERIALIZABLE; порядок блокировок `users → slots → appointments → medical_cases → examinations → athlete_profiles`; Argon2 и сеть вне критических секций
4. Права по `docs/03_matrix.md` (RBAC в `app/core/rbac.py`); чужие данные → 404, ограничение в SQL; тренер не видит диагнозы
5. Время: UTC в БД, Europe/Moscow на экране; ввод дат `ДД.ММ.ГГГГ`, время `ЧЧ:ММ`
6. Фронтенд: правила Hallmark (`~/.agents/skills/hallmark`), токены вместо литералов, без inline-стилей/JS, `|tojson` для данных в Alpine, a11y
7. Секреты только в `.env`, не в git; в логах и аудите нет персональных данных; `seed-demo` только локально

## Статус (обновлять перед каждым /clear, ≤ 10 строк)
- Готово: каркас, этап 1 (auth, пользователи, регистрация спортсмена) — закоммичены; дизайн Almanac; этап 2 (расписание и запись) реализован и проверен (953 теста, ruff чист), ждёт осмотра заказчиком и коммита | Текущий этап: 2 → далее 3 (`docs/stages/stage-3-cases-examinations.md`, спека v1.2 готова)
- Готовые модули: auth, users, schedule (слоты, запись, отмена, приход, неявка, страницы) | Заглушки 501: cases, examinations, conclusions (этапы 3–4)
- Открытые решения/ASSUMPTION: перед деплоем — `docs/stages/pre-deploy-checklist.md` (CSP, TLS, секреты, бэкапы); этап 3: дело обязательно для записи (поправить тесты этапа 2), нагрузочный тест и осмотры без специальности вносит только спортврач
