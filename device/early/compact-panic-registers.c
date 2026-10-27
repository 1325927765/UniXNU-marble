/* Diagnostic-only panic witness with two raw Darwin ARM64 argument slots.
 * Panic(fmt, ...) uses the entry SP; common funnel uses va_list * in x1.
 * Read only aligned, translated normal-memory slots; never dereference %s.
 */
typedef unsigned long u64;
typedef unsigned int u32;
struct vc_info { u32 h,w,depth,rb; u64 base; };
struct canvas { u64 base; u32 w,rb,x,y,end; };
extern const u64 gFont[];

static int mapped(u64 a, int write, int normal) {
    u64 par;
    if (a < 0xffff000000000000UL) return 0;
    if (write) __asm__ volatile("at s1e1w, %1; isb; mrs %0, par_el1" : "=r"(par) : "r"(a) : "memory");
    else __asm__ volatile("at s1e1r, %1; isb; mrs %0, par_el1" : "=r"(par) : "r"(a) : "memory");
    return !(par & 1) && (!normal || (par >> 60));
}
static int slot(const u64 *p) {
    return !((u64)p&7) && mapped((u64)p,0,1) && mapped((u64)p+7,0,1);
}
static void put(struct canvas *g, unsigned char c) {
    if (c=='\n' || g->x+18>g->w) {g->x=0;g->y+=42;}
    if (c=='\n' || g->y+36>g->end) return;
    if (c<32 || c>126) c=' ';
    u64 glyph=gFont[c-32];
    for (u32 row=0;row<12;row++) {
        u32 bits=row<6 ? (u32)(glyph>>32)>>(row*5) : (u32)glyph>>((row-6)*5);
        for (u32 col=0;col<5;col++) if ((bits>>col)&1)
            for (u32 dy=0;dy<3;dy++) for (u32 dx=0;dx<3;dx++)
                *(volatile u32 *)(g->base+(u64)(g->y+row*3+dy)*g->rb+(g->x+col*3+dx)*4)=0xffffffff;
    }
    g->x+=18;
}
static void text(struct canvas *g,const char *p) {while (*p) put(g,*p++);}
static void hex(struct canvas *g,const char *label,u64 value) {
    text(g,label);
    for (int shift=60;shift>=0;shift-=4) put(g,"0123456789abcdef"[(value>>shift)&15]);
}

__attribute__((naked,noreturn,section(".text.a_entry")))
void panic_screen(const char *fmt) {
    __asm__ volatile("mov x1, sp\nmov x2, #0\nb panic_screen_main");
}
__attribute__((naked,noreturn,section(".text.a_common")))
void panic_screen_common(void) {
    __asm__ volatile("mov x2, #1\nb panic_screen_main");
}
__attribute__((used,noreturn))
void panic_screen_main(const char *fmt,const u64 *args,u64 indirect) {
    /* Capture exception registers before rendering; ARG0 is the saved PC for
     * the observed undefined-instruction format. ELR is supplemental only. */
    u64 esr,elr;
    __asm__ volatile("msr daifset, #15; mrs %0, esr_el1; mrs %1, elr_el1" : "=r"(esr),"=r"(elr) :: "memory");
    if (indirect) args=slot(args) ? (const u64 *)*args : (void *)0;
    volatile struct vc_info *v=(void *)VINFO;
    if (mapped(VINFO,0,1) && mapped(VINFO+23,0,1)) {
        u32 w=v->w,h=v->h,rb=v->rb;u64 base=v->base;
        if (v->depth==32 && w>=320 && w<=4096 && h>=480 && h<=4096 &&
            rb>=w*4 && rb<=65536 && !(rb&3) && !(base&3) &&
            base>=0xffff000000000000UL && base+(u64)h*rb>=base) {
            struct canvas g={base,w,rb,0,3*h/16,3*h/4};u64 last=0;
            for (u32 y=g.y;y<g.end;y++) for (u32 x=0;x<w;x++) {
                u64 a=base+(u64)y*rb+x*4;
                if ((a&~4095UL)!=last) {
                    if (!mapped(a,1,0)) goto reset;
                    last=a&~4095UL;
                }
                *(volatile u32 *)a=0x00ff0000;
            }
            text(&g,"PANIC ");
            for (u32 i=0;i<80;i++) {
                if (!mapped((u64)fmt+i,0,1) || !fmt[i]) break;
                put(&g,fmt[i]);
            }
            if (slot(args)) hex(&g,"\nARG0=",args[0]);else text(&g,"\nARG0 unavailable");
            if (slot((const u64 *)((u64)args+8))) hex(&g,"\nARG1=",args[1]);else text(&g,"\nARG1 unavailable");
            hex(&g,"\nESR =",esr);hex(&g,"\nELR =",elr);
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
