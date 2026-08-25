PYTHON_SCRIPT = src/python/hello.py
C_SRC = src/c/hello.c
C_BIN = build/hello_c

.PHONY: all build-c run-python run-c clean

all: run-python build-c

build-c:
	mkdir -p build
	gcc $(C_SRC) -o $(C_BIN)

serve-api:
	python3 server/app.py

serve-static:
	python3 -m http.server 8000

run-python:
	python3 $(PYTHON_SCRIPT)

run-c: build-c
	./$(C_BIN)

clean:
	rm -rf build __pycache__ src/python/__pycache__
