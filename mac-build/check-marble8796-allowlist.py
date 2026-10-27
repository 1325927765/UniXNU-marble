"""Compile the exact generated lookup and check membership/rejection controls."""
from pathlib import Path
import json
import subprocess
import hashlib

r = Path.home()/'unixnu-marble8796-build'
include = r/'xnu/bsd/kern/marble_ios16_cdhashes.inc'
folder = r/'amfi-vectors'
folder.mkdir(exist_ok=True)
c = '''
#include <stdint.h>
#include <stdbool.h>
#include <string.h>
#include <stdio.h>
#define CS_CDHASH_LEN 20
struct cs_hash { uint8_t type; };
struct cs_blob { unsigned char csb_cdhash[20]; const struct cs_hash *csb_hashtype; };
static uint8_t cs_hash_type(const struct cs_hash *p) { return p->type; }
'''
c += include.read_text()
c += '''
int main(void) {
    struct cs_hash hash;
    struct cs_blob blob = {.csb_hashtype=&hash};
    size_t count = sizeof(marble_ios16_cdhashes)/sizeof(marble_ios16_cdhashes[0]);
    if (marble_ios16_hash_allowed(NULL)) return 1;
    for (size_t i=0;i<count;i++) {
        memcpy(blob.csb_cdhash, marble_ios16_cdhashes[i],20);
        hash.type=marble_ios16_cdhashes[i][20];
        if (!marble_ios16_hash_allowed(&blob)) return 2;
        hash.type=0;
        if (marble_ios16_hash_allowed(&blob)) return 3;
    }
    memset(blob.csb_cdhash,0xff,20); hash.type=2;
    if (marble_ios16_hash_allowed(&blob)) return 4;
    blob.csb_hashtype=NULL;
    if (marble_ios16_hash_allowed(&blob)) return 5;
    printf("%zu members and wrong-type controls passed; unknown/null rejected\\n",count);
}
'''
(folder/'lookup.c').write_text(c)
subprocess.run(['xcrun','clang','-Wall','-Werror','-O2',str(folder/'lookup.c'),'-o',str(folder/'lookup')],check=True)
result = subprocess.check_output([str(folder/'lookup')],text=True).strip()
report = dict(include_sha256=hashlib.sha256(include.read_bytes()).hexdigest(),
              compiled_host_controls=result, full_amfi_or_image4_validation=False)
(folder/'result.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2))
