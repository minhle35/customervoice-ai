.PHONY: dev up down backend worker

up:
	docker compose up -d

down:
	docker compose down

backend:
	docker compose up backend

worker:
	docker compose up worker

