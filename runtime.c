#include <stdint.h>
#include <stddef.h>

// https://filippo.io/linux-syscall-table/
#define SYS_CLOBBERS "rcx","r11","memory"
#define SYS_MMAP 9
#define MAP_ANON 0x20
#define MAP_PRIV 0x2
#define MAP_FIXED_NOREPLACE 0x100000
#define PROT_READ  0x1
#define PROT_WRITE 0x2
#define PROT (PROT_READ | PROT_WRITE)

void simple_mmap(void* addr, size_t length)
{
    register uint64_t r10 __asm__("r10") = MAP_ANON | MAP_PRIV | MAP_FIXED_NOREPLACE;
    register uint64_t r8  __asm__("r8")  = 0;
    register uint64_t r9  __asm__("r9")  = 0;

    asm volatile (
        "syscall"
        : :
            "a"(SYS_MMAP), 
            "D"(addr), 
            "S"(length), 
            "d"(PROT),
            "r"(r10),  // flags = MAP_ANON
            "r"(r8),   // fd    = 0 (does not apply for anon maps)
            "r"(r9)    // pgoff = 0 (does not apply for anon maps)
        : SYS_CLOBBERS
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
    entry_t* ptr = struct_table;

    while (ptr->vaddr)
    {
        simple_mmap(ptr->vaddr, ptr->outer_size);
        ptr++;
    }
}



