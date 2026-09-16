
.PHONY: build runtime run

run: build
	./main

build: runtime
	./bootstrap.py prg/test.lhl
	fasm build.asm build.o
	ld build.o runtime.o -o main -z noexecstack

runtime:
	gcc -g -c runtime.c -o runtime.o -ffreestanding  -O0


