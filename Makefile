.PHONY: fmt lint fast slow

fmt:
	ruff format .

lint:
	ruff check .

fast:
	pytest -q -m "not slow"

slow:
	pytest -q -m slow
