#define _GNU_SOURCE


#include <asm/signal.h>
#include <asm/unistd.h>
#include <asm/mman.h>
#include <linux/mman.h>
#include <asm/siginfo.h>
#include <asm/sigcontext.h>
#include <asm/ucontext.h>

#include <stdint.h>
#include <stddef.h>
#include <stdarg.h>

long syscall(long int kind,  ...)
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
    syscall(__NR_mmap, 
        addr, 
        length,
        PROT_READ | PROT_WRITE, 
        MAP_PRIVATE | MAP_ANONYMOUS | MAP_FIXED_NOREPLACE,
        (uint64_t)0, (uint64_t)0
    );
}

void evil_signal_restore()
{
    syscall(__NR_rt_sigreturn);
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
        .flags    = SA_SIGINFO | SA_RESTORER,
        .mask     = 0,
        .restorer = evil_signal_restore,
    };

    syscall(__NR_rt_sigaction,
        SIGSEGV,
        &sigact,
        NULL,
        sizeof(sigact.mask),
        (uint64_t)0, (uint64_t)0
    );

}



typedef struct {
    void*    base_addr;
    uint64_t size; 

    // mutable as program runs.
    // number of contiguous pages
    // in which table lives.
    uint64_t pages;
} table_entry_t;

extern table_entry_t __table_table[];


void runtime_init()
{
    register_handler();

    table_entry_t* ptr = __table_table;
    while (ptr->base_addr)
    {
        map(ptr->base_addr, ptr->pages * 0x1000);
        ptr++;
    }
}


void handler(int sig, siginfo_t *info, void *ucontext)
{
    void* ptr_addr = info->si_addr;
    struct ucontext* ctx = ucontext;

    // the compiler makes sure of this!
    uint64_t base_addr = ctx->uc_mcontext.rbx;

}


