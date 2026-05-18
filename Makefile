.PHONY: test-interactive
test-interactive:
	export PYTHONBREAKPOINT=ipdb.set_trace
	pytest tests/ -s --pdb -vv

check:
	ruff check

format:
	ruff format
