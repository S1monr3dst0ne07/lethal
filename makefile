
.PHONY: build runtime run

run: build
	./main

trace:
	strace ./main

build: runtime
	./bootstrap.py prg/test.lhl
	fasm build.asm build.o
	ld build.o runtime.o -o main -z noexecstack

runtime:
	gcc -g -c runtime.c -o runtime.o  -O0 \
		-masm=intel \
		-ffreestanding \
		-Wno-varargs 


