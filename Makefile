.PHONY: test-interactive
test:
	export PYTHONBREAKPOINT=ipdb.set_trace
	pytest tests/ -s --pdb -vv
