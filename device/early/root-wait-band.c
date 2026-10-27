/* Diagnostic cyan band when the real "Still waiting for root device" log runs.
 * Uses existing framebuffer translations only, then returns to the original log.
 */
typedef unsigned long u64;
typedef unsigned int u32;
struct video {u32 h,w,depth,rb;u64 base;};
static int readable(u64 a) {
    u64 par;
    __asm__ volatile("at s1e1r, %1; isb; mrs %0, par_el1":"=r"(par):"r"(a):"memory");
    return !(par&1) && (par>>60);
}
__attribute__((section(".text.a_entry"))) void panic_screen(void) {
    volatile struct video *v=(void *)VINFO;
    if (!readable(VINFO) || !readable(VINFO+23)) return;
    u32 w=v->w,h=v->h,rb=v->rb;u64 base=v->base;
    if (v->depth!=32 || w<320 || w>4096 || h<480 || h>4096 ||
        rb<w*4 || rb>65536 || (rb&3) || (base&3) ||
        base<0xffff000000000000UL || base+(u64)rb*h<base) return;
    u64 last=0;
    for (u32 y=3*h/16;y<h/4;y++) for (u32 x=0;x<w;x++) {
        u64 a=base+(u64)y*rb+x*4;
        if ((a&~4095UL)!=last) {
            u64 par;
            __asm__ volatile("at s1e1w, %1; isb; mrs %0, par_el1":"=r"(par):"r"(a):"memory");
            if (par&1) return;
            last=a&~4095UL;
        }
        *(volatile u32 *)a=0x0000ffff;
    }
    __asm__ volatile("dsb sy":::"memory");
}
