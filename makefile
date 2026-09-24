
.PHONY: build runtime run

run: build
	./build

trace:
	strace ./build

build:
	./bootstrap.py compiler.lhl
	fasm -m 1000000 build.asm build 
	chmod +x build


