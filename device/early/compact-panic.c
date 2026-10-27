/* Diagnostic copy only. Show a bounded raw panic format, then reset after 12s.
 * No variadic arguments are read. Both panic entry ABIs keep fmt in x0.
 * AT queries inspect existing translations; they do not create mappings.
 */
typedef unsigned long u64;
typedef unsigned int u32;
struct vc_info { u32 h,w,depth,rb; u64 base; };
extern const u64 gFont[];

static int mapped(u64 a, int write, int normal) {
    u64 par;
    if (a < 0xffff000000000000UL) return 0;
    if (write) __asm__ volatile("at s1e1w, %1; isb; mrs %0, par_el1" : "=r"(par) : "r"(a) : "memory");
    else __asm__ volatile("at s1e1r, %1; isb; mrs %0, par_el1" : "=r"(par) : "r"(a) : "memory");
    return !(par & 1) && (!normal || (par >> 60));
}

__attribute__((noreturn,section(".text.a_entry")))
void panic_screen(const char *fmt) {
    volatile struct vc_info *v=(void *)VINFO;
    if (mapped(VINFO,0,1) && mapped(VINFO+23,0,1)) {
        u32 w=v->w,h=v->h,rb=v->rb;
        u64 base=v->base;
        if (v->depth==32 && w>=320 && w<=4096 && h>=480 && h<=4096 &&
            rb>=w*4 && rb<=65536 && !(rb&3) && !(base&3) && base>=0xffff000000000000UL &&
            base+(u64)h*rb>=base) {
            u32 y0=3*h/16,y1=4*h/16;
            u64 last=0;
            for (u32 y=y0;y<y1;y++) for (u32 x=0;x<w;x++) {
                u64 a=base+(u64)y*rb+x*4;
                if ((a&~4095UL)!=last) {
                    if (!mapped(a,1,0)) goto reset;
                    last=a&~4095UL;
                }
                *(volatile u32 *)a=0x00ff0000;
            }
            u32 x=0,y=y0;
            for (u32 i=0;i<102;i++) {
                unsigned char c;
                if (i<6) c="PANIC "[i];
                else {
                    if (!mapped((u64)fmt+i-6,0,1)) break;
                    c=fmt[i-6];
                    if (!c) break;
                }
                if (x+18>w || c=='\n') { x=0; y+=42; }
                if (y+36>y1) break;
                if (c<32 || c>126) c=' ';
                u64 glyph=gFont[c-32];
                for (u32 row=0;row<12;row++) {
                    u32 bits=(row<6 ? (u32)(glyph>>32)>>(row*5) : (u32)glyph>>((row-6)*5));
                    for (u32 col=0;col<5;col++) if ((bits>>col)&1)
                        for (u32 dy=0;dy<3;dy++) for (u32 dx=0;dx<3;dx++)
                            *(volatile u32 *)(base+(u64)(y+row*3+dy)*rb+(x+col*3+dx)*4)=0xffffffff;
                }
                x+=18;
            }
            __asm__ volatile("dsb sy" ::: "memory");
        }
    }
reset:;
    u64 start,now,hz;
    __asm__ volatile("mrs %0, cntfrq_el0; mrs %1, cntpct_el0" : "=r"(hz),"=r"(start));
    if (hz && hz<=1000000000UL) do {
        __asm__ volatile("mrs %0, cntpct_el0" : "=r"(now));
    } while (now-start<hz*12);
    register u64 x0 __asm__("x0")=0x84000009;
    register u64 x1 __asm__("x1")=0;
    register u64 x2 __asm__("x2")=0;
    register u64 x3 __asm__("x3")=0;
    __asm__ volatile(".global panic_reset_checkpoint\npanic_reset_checkpoint:\nsmc #0" : "+r"(x0),"+r"(x1),"+r"(x2),"+r"(x3) :: "memory");
    for (;;) __asm__ volatile("wfe");
}

#include "Font.h"
__attribute__((section(".text.z_font"))) const u64 gFont[]=GLYPH_FONT;
