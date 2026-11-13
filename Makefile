# GNU make (Windows: winget ezwinports.make). Paid targets pass YES=--yes, e.g. `make pilot YES=--yes`.
PY := .venv/Scripts/python.exe
MODEL ?= primary
VARIANT ?= both
YES ?=
RUNARGS = --model $(MODEL) --turn1-variant $(VARIANT) $(YES)

.PHONY: setup data test wild estimate probe pilot dryrun full analyze

setup:
	py -3.12 -m venv .venv
	$(PY) -m pip install -r requirements.txt
	$(PY) -m pip install -e .

data:
	$(PY) tools/copy_raw.py
	$(PY) -m sor.load

test:
	$(PY) -m pytest -q

wild:
	$(PY) -m sor.wild

estimate:
	$(PY) -m sor.run estimate

probe:
	$(PY) -m sor.run probe --model $(MODEL) $(YES)

pilot:
	$(PY) -m sor.run pilot $(RUNARGS)

dryrun:
	$(PY) -m sor.run dryrun $(RUNARGS)

full:
	$(PY) -m sor.run full $(RUNARGS)

analyze:
	$(PY) -m sor.analyze
