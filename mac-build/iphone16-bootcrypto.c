/* Marble iPhone16 experiment: execute the unchanged, constructor-free original
 * crypto module before EARLY_BOOT kmem crypto users. The emitter fills only this
 * descriptor. OSKext later adopts the actual completed start, once, instead of
 * initializing the global PRNG twice. No POST or crypto result is bypassed.
 * Appended to Apple's APSL-licensed prng_random.c by an explicit build overlay.
 */
#include <kern/startup.h>
#include <mach/kmod.h>
#include <mach-o/loader.h>
#include <libkern/crypto/register_crypto.h>

extern crypto_functions_t g_crypto_funcs;
extern bool crypto_init;

SECURITY_READ_ONLY_LATE(uint64_t) marble_iphone16_crypto_boot[9] = {
    0x4950313643525950ULL, 1, 0, 0, 0, 0, 0, 0, 0
};
SECURITY_READ_ONLY_LATE(kern_return_t) marble_iphone16_crypto_status = KERN_FAILURE;
SECURITY_READ_ONLY_LATE(uint32_t) marble_iphone16_crypto_calls = 0;
SECURITY_READ_ONLY_LATE(uint32_t) marble_iphone16_crypto_adoptions = 0;

static void
marble_iphone16_crypto_bootstrap(void)
{
    uint64_t *d = marble_iphone16_crypto_boot;
    uint32_t mode = 0;
    if (d[0] != 0x4950313643525950ULL || d[1] != 1 || !d[2] || !d[3] ||
        !d[4] || d[5] >= d[6] || d[7] >= d[8] || d[2] < d[7] ||
        d[2] > d[8] - sizeof(kmod_info_t) || d[3] < d[5] || d[3] >= d[6]) {
        panic("iPhone16 crypto: missing or invalid original module descriptor");
    }
    if (g_crypto_funcs || crypto_init || prng_ready || marble_iphone16_crypto_calls) {
        panic("iPhone16 crypto: provider already initialized");
    }
    if (PE_parse_boot_argn("fips_mode", &mode, sizeof(mode)) && mode != 0) {
        panic("iPhone16 crypto requires original complete default POST");
    }
    kmod_info_t *info = (kmod_info_t *)(uintptr_t)d[2];
    struct mach_header_64 *header = (struct mach_header_64 *)(uintptr_t)d[4];
    if (strcmp(info->name, "com.apple.kec.corecrypto") ||
        info->address != d[4] || (uintptr_t)info->start != d[3] ||
        header->magic != MH_MAGIC_64 || header->cputype != 0x100000c ||
        header->cpusubtype != 0 || header->filetype != MH_KEXT_BUNDLE ||
        header->ncmds > 32 || header->sizeofcmds > 8192) {
        panic("iPhone16 crypto: original module identity mismatch");
    }
    uintptr_t command = (uintptr_t)(header + 1), end = command + header->sizeofcmds;
    bool executable = false;
    for (uint32_t i = 0; i < header->ncmds; ++i) {
        struct load_command *lc = (struct load_command *)command;
        if (command > end || end - command < sizeof(*lc) ||
            lc->cmdsize < sizeof(*lc) || lc->cmdsize > end - command) {
            panic("iPhone16 crypto: invalid original load commands");
        }
        if (lc->cmd == LC_SEGMENT_64) {
            struct segment_command_64 *seg = (struct segment_command_64 *)lc;
            if (lc->cmdsize < sizeof(*seg) ||
                seg->nsects > (lc->cmdsize - sizeof(*seg)) / sizeof(struct section_64)) {
                panic("iPhone16 crypto: invalid original segment");
            }
            if (!strcmp(seg->segname, "__TEXT_EXEC") && seg->initprot == 5 &&
                !(seg->maxprot & 2) && seg->vmaddr == d[5] &&
                seg->vmsize == d[6] - d[5]) {
                executable = true;
            }
            struct section_64 *section = (struct section_64 *)(seg + 1);
            for (uint32_t n = 0; n < seg->nsects; ++n) {
                if (!strcmp(section[n].sectname, "__mod_init_func") && section[n].size) {
                    panic("iPhone16 early crypto requires a constructor-free C module");
                }
            }
        }
        command += lc->cmdsize;
    }
    if (command != end || !executable) {
        panic("iPhone16 crypto: start address lacks original executable segment");
    }
    ++marble_iphone16_crypto_calls;
    marble_iphone16_crypto_status = info->start(info, NULL);
    if (marble_iphone16_crypto_status != KERN_SUCCESS || !crypto_init || !prng_ready ||
        (uintptr_t)g_crypto_funcs < d[7] || (uintptr_t)g_crypto_funcs >= d[8]) {
        panic("iPhone16 original crypto initialization failed: %d", marble_iphone16_crypto_status);
    }
}
STARTUP(EARLY_BOOT, STARTUP_RANK_FIRST, marble_iphone16_crypto_bootstrap);

bool
marble_iphone16_adopt_boot_crypto(kmod_info_t *info, kern_return_t *result)
{
    if (strcmp(info->name, "com.apple.kec.corecrypto")) {
        return false;
    }
    uint64_t *d = marble_iphone16_crypto_boot;
    if (info->address != d[4] || (uintptr_t)info->start != d[3] ||
        marble_iphone16_crypto_calls != 1 || marble_iphone16_crypto_adoptions ||
        marble_iphone16_crypto_status != KERN_SUCCESS || !crypto_init || !prng_ready ||
        (uintptr_t)g_crypto_funcs < d[7] || (uintptr_t)g_crypto_funcs >= d[8]) {
        panic("iPhone16 crypto: OSKext adoption does not match the completed original start");
    }
    ++marble_iphone16_crypto_adoptions;
    *result = marble_iphone16_crypto_status;
    return true;
}
