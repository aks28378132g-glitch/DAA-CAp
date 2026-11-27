.PHONY: run test bench bench-all

run:        ## launch the web UI on http://127.0.0.1:8000
	python3 server.py

test:       ## run the unit + integration tests
	python3 -m unittest discover -s tests -v

bench:      ## Small / Medium / Large benchmark
	python3 benchmark.py

bench-all:  ## adds repetitive, random, Unicode, single-char and empty cases
	python3 benchmark.py --extended
