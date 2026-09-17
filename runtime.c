#define _GNU_SOURCE
#include <unistd.h>

#include <sys/syscall.h>
#include <sys/types.h>
#include <sys/mman.h>

#include <stdint.h>
#include <stddef.h>
#include <stdarg.h>
#include <signal.h>

inline long syscall(long int kind,  ...)
{
    // literally the only reason this uses va
    // is to shut up the type checker.
    va_list args;
    va_start(args, 6);

    uint64_t p1 = va_arg(args, uint64_t);
    uint64_t p2 = va_arg(args, uint64_t);
    uint64_t p3 = va_arg(args, uint64_t);
    uint64_t p4 = va_arg(args, uint64_t);
    uint64_t p5 = va_arg(args, uint64_t);
    uint64_t p6 = va_arg(args, uint64_t);
    va_end(args);

    register uint64_t r10 __asm__("r10") = p4;
    register uint64_t r8  __asm__("r8")  = p5;
    register uint64_t r9  __asm__("r9")  = p6;

    uint64_t ret;
    asm volatile (
        "syscall"
        : "=a"(ret)
        : "a"(kind), "D"(p1), "S"(p2), "d"(p3), "r"(r10), "r"(r8), "r"(r9)
        : "rcx", "r11", "memory"
    );
    return ret;
}


void map(void* addr, size_t length)
{
    syscall(SYS_mmap, 
        addr, 
        length, 
        PROT_READ | PROT_WRITE, 
        MAP_ANON | MAP_PRIVATE | MAP_FIXED_NOREPLACE,
        (uint64_t)0, (uint64_t)0
    );
}


void handler(int sig, siginfo_t *info, void *ucontext);
void register_handler()
{
    struct {
        void (*handler)(int sig, siginfo_t *info, void *ucontext);;
        unsigned long flags;
        void (*restorer)(void);
        unsigned long mask;
    } sigact = {
        .handler  = handler,
        .flags    = SA_SIGINFO,
        .mask     = 0,
        .restorer = NULL
    };

    syscall(SYS_rt_sigaction,
        SIGSEGV,
        &sigact,
        NULL,
        sizeof(sigact.mask),
        (uint64_t)0, (uint64_t)0
    );

}



typedef struct {
    void*    vaddr;
    uint64_t inner_size;
    uint64_t outer_size;
    uint64_t count;
} entry_t;

extern entry_t struct_table[];


void runtime_init()
{
    register_handler();

    entry_t* ptr = struct_table;
    while (ptr->vaddr)
    {
        map(ptr->vaddr, ptr->outer_size);
        ptr++;
    }
}


void handler(int sig, siginfo_t *info, void *ucontext)
{

}


