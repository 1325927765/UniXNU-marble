/* Built-in provider: Apple libpthread-514.100.2, paired with xnu-8796.141.3. */
#if defined(ARM64_BOARD_CONFIG_MARBLE)
#include "marble_pthread_compat.h"
#include "marble_libpthread/kern/kern_init.c"

/* Keep the provider's full layout within the kernel's reserved storage. */
_Static_assert(sizeof(struct ksyn_waitq_element) == 56,
    "update MARBLE ksyn storage in sys/pthread_internal.h");

/* Restore the startup interface after compiling the provider's kext code. */
#define XNU_KERNEL_PRIVATE 1
#include <kern/startup.h>
#include <pexpert/pexpert.h>

__startup_func
static void
marble_pthread_register(void)
{
    kern_return_t kr = marble_pthread_start(NULL, NULL);
    if (kr != KERN_SUCCESS || marble_pthread_kern == NULL) {
        panic("MARBLE: pthread provider registration failed: %d", kr);
    }
    kprintf("MARBLE pthread: libpthread-514.100.2 registered\n");
}
STARTUP(EARLY_BOOT, STARTUP_RANK_SECOND, marble_pthread_register);
#endif /* ARM64_BOARD_CONFIG_MARBLE */
