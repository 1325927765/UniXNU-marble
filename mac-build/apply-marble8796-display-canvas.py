"""Make the logical IOMobileFramebuffer size agree with the iPhone ADT canvas."""
from pathlib import Path
import sys

p = Path(sys.argv[1]) / 'iokit/Kernel/arm/MarbleFramebuffer.cpp'
s = p.read_text()
changes = [
    ('#define MARBLE_FB_DOT_PITCH              395     /* ppi, 6.67" 1080x2400 */',
     '#define MARBLE_FB_DOT_PITCH              458     /* iPhone X logical canvas */\n'
     '#define MARBLE_FB_LOGICAL_W              1125\n'
     '#define MARBLE_FB_LOGICAL_H              2436'),
    ('\tuint32_t      fWidth, fHeight, fRowBytes;\n',
     '\tuint32_t      fWidth, fHeight, fRowBytes;\n'
     '\tuint32_t      fLogicalW, fLogicalH;\n'
     '\tint32_t       fOffX, fOffY;\n'),
    ('\tfRowBytes = (uint32_t)video.v_rowBytes;\n'
     '\tif (fPhys == 0 || fWidth == 0 || fHeight == 0 || fRowBytes < fWidth * 4) {',
     '\tfRowBytes = (uint32_t)video.v_rowBytes;\n'
     '\tint native = 0;\n'
     '\tPE_parse_boot_argn("marblefb_native", &native, sizeof(native));\n'
     '\tfLogicalW = fWidth;\n'
     '\tfLogicalH = fHeight;\n'
     '\tif (!native && fWidth <= MARBLE_FB_LOGICAL_W && fHeight <= MARBLE_FB_LOGICAL_H) {\n'
     '\t\tfLogicalW = MARBLE_FB_LOGICAL_W;\n'
     '\t\tfLogicalH = MARBLE_FB_LOGICAL_H;\n'
     '\t}\n'
     '\tfOffX = (int32_t)(fLogicalW - fWidth) / 2;\n'
     '\tfOffY = (int32_t)(fLogicalH - fHeight) / 2;\n'
     '\tif (fPhys == 0 || fWidth == 0 || fHeight == 0 || fRowBytes < fWidth * 4) {'),
    ('\tIOLog("MARBLE FB: AppleCLCD %ux%u stride %u at 0x%llx, default surface %u\\n",\n'
     '\t    fWidth, fHeight, fRowBytes, fPhys, fSurface->id);',
     '\tIOLog("MARBLE FB: AppleCLCD %ux%u stride %u at 0x%llx, default surface %u, presented as %ux%u\\n",\n'
     '\t    fWidth, fHeight, fRowBytes, fPhys, fSurface->id, fLogicalW, fLogicalH);'),
    ('\t\tif (w > (int32_t)s->width - sx) {',
     '\t\tdx -= fOffX;\n'
     '\t\tdy -= fOffY;\n'
     '\t\tif (dx < 0) { sx -= dx; w += dx; dx = 0; }\n'
     '\t\tif (dy < 0) { sy -= dy; h += dy; dy = 0; }\n'
     '\t\tif (w > (int32_t)s->width - sx) {'),
    ('\t\tout[0] = fFB->fWidth;\n'
     '\t\tout[1] = fFB->fHeight;',
     '\t\tout[0] = fFB->fLogicalW;\n'
     '\t\tout[1] = fFB->fLogicalH;'),
]
for old, new in changes:
    count = s.count(old)
    if count != 1:
        raise RuntimeError(f'{p}: expected one match, found {count}: {old[:80]!r}')
    s = s.replace(old, new, 1)
p.write_text(s)
