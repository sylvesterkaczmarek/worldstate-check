.PHONY: test smoke

test:
	python -m pytest

smoke:
	python -m worldstate_check.cli demo --scenario verified
