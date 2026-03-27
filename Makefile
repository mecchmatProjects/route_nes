PYTHON = .venv/Scripts/python.exe

.PHONY: all test test-load test-exclude test-special test-phase1 test-phase2 test-postprocess venv clean

all: test

venv:
	py -3 -m venv .venv
	$(PYTHON) -m pip install --upgrade pip

test: test-load test-exclude test-special test-phase1 test-phase2 test-postprocess
	@echo ============================================================
	@echo   ALL TEST SUITES PASSED
	@echo ============================================================

test-load:
	$(PYTHON) test_load_validate.py

test-exclude:
	$(PYTHON) test_exclude_exceptions.py

test-special:
	$(PYTHON) test_special_routes.py

test-phase1:
	$(PYTHON) test_phase1.py

test-phase2:
	$(PYTHON) test_phase2.py

test-postprocess:
	$(PYTHON) test_postprocess.py

clean:
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -name "*.pyc" -delete
