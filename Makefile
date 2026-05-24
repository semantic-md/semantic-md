.PHONY: test-interactive
test-interactive:
	export PYTHONBREAKPOINT=ipdb.set_trace
	pytest tests/test_convert.py::test_convert[recipe] -s --pdb -vv
#	pytest tests -s --pdb -vv

.PHONY: check
check:
	ruff check

.PHONY: check-fix
check-fix:
	ruff check --fix

.PHONY: format
format:
	ruff format

.PHONY: build
build:
	python -m build

.PHONY: upload
upload:
	python -m twine upload dist/*
