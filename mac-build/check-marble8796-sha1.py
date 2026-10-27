"""Host-check the actual kernel SHA1 context adapter against hashlib vectors."""
import hashlib
import json
from pathlib import Path
import subprocess

root = Path.home() / 'unixnu-marble8796-build'
source = root / 'xnu/libkern/crypto/corecrypto_sha1.c'
text = source.read_text()
# Keep the actual adapter and legacy context; omit unrelated kernel hardware hook.
adapter = text[text.index('static uint64_t'):text.index('/* This is not publicised')]
header = (root / 'xnu/libkern/libkern/crypto/sha1.h').read_text()
context = header[header.index('typedef struct sha1_ctxt'):header.index('/* For compatibility')]
folder = root / 'sha1-vectors'
folder.mkdir(exist_ok=True)
c = '#include <stdint.h>\n#include <sys/types.h>\n#include <string.h>\n#include <stdio.h>\n'
c += '#define ARM64_BOARD_CONFIG_MARBLE 1\n' + context + adapter
c += '''
int main(void) {
    unsigned char block[997], digest[20];
    SHA1_CTX ctx;
    SHA1Init(&ctx);
    size_t n;
    while ((n = fread(block, 1, sizeof(block), stdin))) SHA1Update(&ctx, block, n);
    SHA1Final(digest, &ctx);
    for (int i=0; i<20; i++) printf("%02x", digest[i]);
    puts("");
}
'''
(folder / 'adapter.c').write_text(c)
crypto = root / 'xnu/libkern/crypto'
subprocess.run(['xcrun', 'clang', '-O2', '-I' + str(crypto),
                '-I' + str(crypto / 'marble_bearssl/inc'),
                '-I' + str(crypto / 'marble_bearssl/src'), str(folder / 'adapter.c'),
                str(crypto / 'marble_bearssl/src/hash/sha1.c'),
                str(crypto / 'marble_bearssl/src/codec/dec32be.c'),
                str(crypto / 'marble_bearssl/src/codec/enc32be.c'),
                '-o', str(folder / 'sha1')], check=True)
results = []
for data in [b'', b'abc', b'a'*55, b'a'*56, b'a'*63, b'a'*64,
             b'a'*65, bytes(range(256))*17, b'a'*1000000]:
    expected = hashlib.sha1(data).hexdigest()
    actual = subprocess.check_output([str(folder / 'sha1')], input=data).decode().strip()
    assert actual == expected, (len(data), actual, expected)
    results.append(dict(bytes=len(data), sha1=actual, passed=True))
report = dict(source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
              host_adapter_vectors=results, kernel_runtime_proven=False)
(folder / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps(report, indent=2))
