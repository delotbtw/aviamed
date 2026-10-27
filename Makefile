.PHONY: help env build up down restart logs ps migrate admin seed shell-db test test-db test-db-stop lint fmt reset

ADMIN_EMAIL ?= admin@example.com
# ADMIN_PASSWORD has no default: pass it via the environment (ADMIN_PASSWORD=... make admin), not as a make argument.
export ADMIN_PASSWORD  # passed to containers by name (-e ADMIN_PASSWORD), never inlined in the command line

help:  ## Список команд
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  make %-14s %s\n", $$1, $$2}'

env:  ## Создать .env из .env.example, если его нет
	@test -f .env || cp .env.example .env

build: env  ## Собрать образы
	docker compose build

up: env  ## Собрать и поднять всё (http://localhost)
	docker compose up --build -d
	@echo "Открой http://localhost"
	@echo "Первый админ: ADMIN_PASSWORD='<пароль>' make admin ADMIN_EMAIL=you@example.com"
	@echo "Демо-пользователи (ТОЛЬКО локальный стенд): make seed CONFIRM=local"

down:  ## Остановить (данные БД сохраняются)
	docker compose down

restart: down up  ## Перезапустить

logs:  ## Логи приложения (Ctrl+C — выйти)
	docker compose logs -f app nginx

ps:  ## Состояние контейнеров
	docker compose ps

migrate:  ## Применить миграции вручную
	docker compose run --rm migrate

admin:  ## Создать админа: ADMIN_PASSWORD='...' make admin ADMIN_EMAIL=a@b.ru
	@test -n "$$ADMIN_PASSWORD" || { echo "Задайте пароль через окружение: ADMIN_PASSWORD='...' make admin"; exit 1; }
	@docker compose exec -e ADMIN_PASSWORD app python -m app.cli create-admin --email $(ADMIN_EMAIL)
	@echo "Вход: $(ADMIN_EMAIL) / пароль из ADMIN_PASSWORD"

# ТОЛЬКО ДЛЯ ЛОКАЛЬНОГО СТЕНДА: аккаунты с публично известным паролем. В compose DEBUG=false, поэтому нужен --force,
# который передаётся только после явного подтверждения CONFIRM=local.
seed:  ## Демо-данные (только локальный стенд!): make seed CONFIRM=local
	@test "$(CONFIRM)" = "local" || { echo "Создаёт аккаунты с публичным паролем. Только для локального стенда: make seed CONFIRM=local"; exit 1; }
	docker compose exec app python -m app.cli seed-demo --force

shell-db:  ## psql в базе
	docker compose exec postgres sh -c 'psql -U "$$POSTGRES_USER" "$$POSTGRES_DB"'

test-db:  ## Поднять тестовый Postgres (порт 55432)
	@docker inspect medcenter-test-pg >/dev/null 2>&1 || docker run -d --rm --name medcenter-test-pg -p 55432:5432 \
		-e POSTGRES_USER=medcenter -e POSTGRES_PASSWORD=medcenter -e POSTGRES_DB=medcenter_test \
		--tmpfs /var/lib/postgresql/data postgres:17-alpine

test-db-stop:  ## Остановить тестовый Postgres
	-docker stop medcenter-test-pg

test: test-db  ## Прогнать тесты
	uv run pytest

lint:  ## ruff check + format --check
	uv run ruff check . && uv run ruff format --check .

fmt:  ## ruff format
	uv run ruff format .

reset:  ## Снести контейнеры И данные БД, поднять заново
	docker compose down -v
	$(MAKE) up
