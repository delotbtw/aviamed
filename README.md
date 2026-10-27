# АвиаМед

Система допуска спортсменов (медцентр вуза). Модульный монолит: FastAPI + Jinja2 + SQLAlchemy 2.x (async) + PostgreSQL + Redis.
Документация: [docs/](docs/) (архитектура - `02_arch.md`, роли - `03_matrix.md`, модель данных - `04-data-model.md`).

Статус: архитектурный скелет. Модели, миграция, RBAC, JWT-вход, чтение справочников и `/health` работают;
остальная бизнес-логика - заглушки (HTTP 501 и `TODO` в сервисах).

## Запуск локально

```bash
cp .env.example .env            # поменять секреты
uv sync
# PostgreSQL и Redis должны быть доступны (например, docker compose up -d postgres redis)
uv run alembic upgrade head
uv run uvicorn app.main:app --reload
```

- http://localhost:8000/health, http://localhost:8000/docs, админка: `/admin` (только роль admin).

## Запуск в Docker

```bash
cp .env.example .env
docker compose up --build
docker compose exec app alembic upgrade head
```

Nginx слушает порт 80 (TLS - TODO до пилота).

## Тесты и линтер

```bash
uv run pytest
uv run ruff check . && uv run ruff format --check .
```

## Миграции

```bash
uv run alembic revision --autogenerate -m "message"
uv run alembic upgrade head
```

Любое изменение схемы - только через миграцию. Новые модели нужно импортировать в `app/models/__init__.py`.

## Структура

```
app/
  main.py            FastAPI, роутеры, /health, SQLAdmin
  core/              config, db, redis, security (argon2, JWT), rbac (роли и матрица прав), deps, templating
  models/            SQLAlchemy-модели по docs/04
  repositories/      BaseRepository (ABC) + наследники; все запросы только здесь
  services/          сквозная логика (status.py - единая точка смены статусов + status_history)
  auth users reference schedule cases examinations conclusions audit/
                     router.py (представление), service.py (бизнес-логика), schemas.py (Pydantic)
  admin/             SQLAdmin (рабочие таблицы только на чтение)
  templates/ static/ Jinja2 и статика
migrations/          Alembic (async env.py, URL из DATABASE_URL)
nginx/               nginx.conf (rate limit, прокси, статика)
tests/               pytest
```

Слои: router -> service -> repository -> model. Роутер проверяет роль (`require_roles` / `require_action`),
принадлежность данных проверяет сервис. Матрица прав - данные в `app/core/rbac.py` (`PERMISSIONS`).
