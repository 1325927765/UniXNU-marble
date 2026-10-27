#include <dlfcn.h>
#include <stdio.h>

typedef int (*extract_fn)(const char *, const char *, void (^)(unsigned, unsigned));

int
main(int argc, char **argv)
{
    if (argc != 4) {
        fprintf(stderr, "usage: %s dsc_extractor.bundle cache output-dir\n", argv[0]);
        return 2;
    }
    void *bundle = dlopen(argv[1], RTLD_LAZY);
    if (bundle == NULL) {
        fprintf(stderr, "dlopen: %s\n", dlerror());
        return 3;
    }
    extract_fn extract = (extract_fn)dlsym(bundle,
        "dyld_shared_cache_extract_dylibs_progress");
    if (extract == NULL) {
        fprintf(stderr, "dlsym: %s\n", dlerror());
        return 4;
    }
    return extract(argv[2], argv[3], ^(unsigned current, unsigned total) {
        if ((current & 127U) == 0 || current == total)
            fprintf(stderr, "%u/%u\n", current, total);
    });
}
