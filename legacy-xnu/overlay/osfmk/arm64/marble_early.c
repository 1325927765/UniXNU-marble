/* No physical framebuffer writes before the ADT serial console is configured. */
#include <arm64/marble_early.h>
#if defined(MARBLE)
void marble_early_mark(unsigned int stage, const char *label) { (void)stage; (void)label; }
void marble_early_putc(char c) { (void)c; }
void marble_early_panic(const char *fmt, va_list *args) { (void)fmt; (void)args; }
void marble_early_relocate(uint64_t base) { (void)base; }
void marble_early_disable(void) {}
#endif
