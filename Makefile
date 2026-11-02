.PHONY: help env build up down restart logs ps migrate admin seed seed-demo shell-db test test-db test-db-stop lint fmt reset

ADMIN_EMAIL ?= admin@example.com
# ADMIN_PASSWORD has no default: pass it via the environment (ADMIN_PASSWORD=... make admin), not as a make argument.
export ADMIN_PASSWORD  # passed to containers by name (-e ADMIN_PASSWORD), never inlined in the command line

help:  ## Список команд
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  make %-14s %s\n", $$1, $$2}'

env:  ## Создать .env из .env.example и сгенерировать SECRET_KEY, если там заглушка
	@test -f .env || cp .env.example .env
	@if grep -qi '^SECRET_KEY=.*change-me' .env; then \
		key=$$(openssl rand -hex 32); \
		sed -i.bak "s|^SECRET_KEY=.*|SECRET_KEY=$$key|" .env && rm -f .env.bak; \
		echo "SECRET_KEY сгенерирован в .env"; \
	fi

build: env  ## Собрать образы
	docker compose build

up: env  ## Собрать и поднять всё (http://localhost)
	docker compose up --build -d
	@echo "Открой http://localhost"
	@echo "Первый админ: ADMIN_PASSWORD='<пароль>' make admin ADMIN_EMAIL=you@example.com"
	@echo "Демо-пользователи (ТОЛЬКО локальный стенд): make seed-demo CONFIRM=local"

down:  ## Остановить всё, включая тестовую БД (данные БД сохраняются)
	docker compose --profile test down

restart: down up  ## Перезапустить

logs:  ## Логи приложения (Ctrl+C — выйти)
	docker compose logs -f app nginx

ps:  ## Состояние контейнеров (включая тестовую БД)
	docker compose --profile test ps

status: ps  ## Алиас для ps

migrate:  ## Применить миграции вручную
	docker compose run --rm migrate

admin:  ## Создать админа: ADMIN_PASSWORD='...' make admin ADMIN_EMAIL=a@b.ru
	@test -n "$$ADMIN_PASSWORD" || { echo "Задайте пароль через окружение: ADMIN_PASSWORD='...' make admin"; exit 1; }
	@docker compose exec -e ADMIN_PASSWORD app python -m app.cli create-admin --email $(ADMIN_EMAIL)
	@echo "Вход: $(ADMIN_EMAIL) / пароль из ADMIN_PASSWORD"

# ТОЛЬКО ДЛЯ ЛОКАЛЬНОГО СТЕНДА: аккаунты с публично известным паролем. В compose DEBUG=false, поэтому нужен --force,
# который передаётся только после явного подтверждения CONFIRM=local.
# Вторым ключом идёт ALLOW_DEMO_SEED=1 (в боевом .env его нет, CLI без него отказывает); DEMO_PASSWORD пробрасывается по имени.
seed-demo:  ## Демо-данные (только локальный стенд!): make seed-demo CONFIRM=local
	@test "$(CONFIRM)" = "local" || { echo "Создаёт аккаунты с публичным паролем. Только для локального стенда: make seed-demo CONFIRM=local"; exit 1; }
	docker compose exec -e ALLOW_DEMO_SEED=1 -e DEMO_PASSWORD app python -m app.cli seed-demo --force

seed: seed-demo  ## Алиас для seed-demo

shell-db:  ## psql в базе
	docker compose exec postgres sh -c 'psql -U "$$POSTGRES_USER" "$$POSTGRES_DB"'

test-db:  ## Поднять тестовый Postgres (127.0.0.1:55432, profile test)
	docker compose --profile test up -d --wait postgres-test

test-db-stop:  ## Остановить и удалить только тестовый Postgres
	docker compose --profile test rm -sf postgres-test

test: test-db  ## Прогнать тесты (поднимает тестовую БД)
	uv run pytest

lint:  ## ruff check + format --check
	uv run ruff check . && uv run ruff format --check .

fmt:  ## ruff format
	uv run ruff format .

reset:  ## Снести контейнеры И данные БД, поднять заново
	docker compose --profile test down -v
	$(MAKE) up
