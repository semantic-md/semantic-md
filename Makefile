.PHONY: test
test:
	export PYTHONBREAKPOINT=ipdb.set_trace
	pytest tests/ -s
