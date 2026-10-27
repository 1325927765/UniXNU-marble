"""Opt-in, bounded IOKit request/response logging for two graphics processes."""
from pathlib import Path
from datetime import datetime
import argparse
import hashlib
import json

ROOT = Path.home() / 'unixnu-marble8796-build'
HELPER = r'''
/* Dedicated budget: unrelated device-tree probes cannot exhaust this trace. */
static uint32_t marble_graphics_service_lines;
static bool
marble_graphics_caller(char *name, size_t size)
{
	uint32_t enabled = 0;
	if (!PE_parse_boot_argn("marble_graphics_services", &enabled, sizeof(enabled)) || enabled != 1) {
		return false;
	}
	proc_selfname(name, (int)size);
	name[size - 1] = 0;
	return strcmp(name, "backboardd") == 0 || strcmp(name, "SpringBoard") == 0;
}

static void
marble_graphics_emit(const char *name, const char *line)
{
	uint32_t old = __atomic_load_n(&marble_graphics_service_lines, __ATOMIC_RELAXED);
	do {
		if (old >= 192) {
			return;
		}
	} while (!__atomic_compare_exchange_n(&marble_graphics_service_lines,
	    &old, old + 1, false, __ATOMIC_RELAXED, __ATOMIC_RELAXED));
	IOLog("MARBLE GFX %u %s[%d]: %s\n", old + 1, name, proc_selfpid(), line);
}

static void
marble_graphics_matching(const char *kind, OSObject *object, unsigned int count)
{
	char name[32] = {0};
	char line[384];
	if (!marble_graphics_caller(name, sizeof(name))) {
		return;
	}
	OSDictionary *dict = OSDynamicCast(OSDictionary, object);
	if (dict == NULL) {
		return;
	}
	const char *keys[] = {"IOProviderClass", "IONameMatch", "IOResourceMatch", "IOPropertyMatch"};
	for (unsigned int i = 0; i < sizeof(keys) / sizeof(keys[0]); i++) {
		OSObject *value = dict->getObject(keys[i]);
		if (value == NULL) {
			continue;
		}
		OSString *string = OSDynamicCast(OSString, value);
		OSSerialize *ser = NULL;
		const char *text = string != NULL ? string->getCStringNoCopy() : NULL;
		if (text == NULL) {
			ser = OSSerialize::withCapacity(128);
			if (ser != NULL && value->serialize(ser)) {
				text = ser->text();
			}
		}
		snprintf(line, sizeof(line), "%s count=%u %s=%.240s", kind, count, keys[i], text != NULL ? text : "?");
		for (unsigned int j = 0; line[j] != 0; j++) {
			if (line[j] == '\n' || line[j] == '\r') line[j] = ' ';
		}
		marble_graphics_emit(name, line);
		OSSafeReleaseNULL(ser);
	}
}

static void
marble_graphics_service(const char *kind, IOService *service, uint64_t value)
{
	char name[32] = {0};
	char line[256];
	if (!marble_graphics_caller(name, sizeof(name))) {
		return;
	}
	snprintf(line, sizeof(line), "%s service=%.96s class=%.80s value=0x%llx",
	    kind, service->getName(), service->getMetaClass()->getClassName(), value);
	marble_graphics_emit(name, line);
}
'''


def once(text, old, new):
    if text.count(old) != 1:
        raise ValueError(f'expected one anchor, got {text.count(old)}: {old[:85]!r}')
    return text.replace(old, new, 1)


def transform(text):
    if 'marble_graphics_service_lines' in text:
        raise ValueError('trace already installed')
    text = once(text, '#include <libkern/c++/OSSerialize.h>',
                '#include <libkern/c++/OSSerialize.h>\n#include <pexpert/pexpert.h>')
    anchor = 'static void\nmarble_disp_matching(const char *kind, OSObject *dict, unsigned int count)\n{'
    text = once(text, anchor, HELPER + '\n' + anchor + '\n\tmarble_graphics_matching(kind, dict, count);')
    for suffix, arguments in [('waitQuiet', 'timeoutNS'), ('waitQuietWithOptions', 'timeoutNS, options')]:
        old = f'\treturn service->{suffix}({arguments});'
        text = once(text, old, '#if defined(ARM64_BOARD_CONFIG_MARBLE)\n'
                    f'\tmarble_graphics_service("{suffix}-begin-ns", service, timeoutNS);\n'
                    '#endif\n'
                    f'\tkern_return_t result = service->{suffix}({arguments});\n'
                    '#if defined(ARM64_BOARD_CONFIG_MARBLE)\n'
                    f'\tmarble_graphics_service("{suffix}-end", service, (uint32_t)result);\n'
                    '#endif\n\treturn result;')
    start = text.index('is_io_service_open_extended(')
    end = text.index('/* Routine io_service_close */', start)
    part = text[start:end]
    part = once(part, '\tCHECK( IOService, _service, service );',
                '\tCHECK( IOService, _service, service );\n'
                '#if defined(ARM64_BOARD_CONFIG_MARBLE)\n'
                '\tmarble_graphics_service("open-begin-type", service, connect_type);\n#endif')
    part = once(part, '\t*result = res;\n', '\t*result = res;\n'
                '#if defined(ARM64_BOARD_CONFIG_MARBLE)\n'
                '\tmarble_graphics_service("open-end", service, (uint32_t)res);\n#endif\n')
    return text[:start] + part + text[end:]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=ROOT / 'xnu/iokit/Kernel/IOUserClient.cpp')
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    original = args.source.read_text()
    changed = transform(original)
    print('PASS: exact two process names, explicit boot argument, 192-line atomic budget')
    print('PASS: existing matching, open and wait calls and return values preserved')
    if not args.apply:
        print('Dry run; no files changed')
        return
    backup = ROOT / 'trace-backups' / datetime.now().strftime('%Y%m%d-graphics-services-%H%M%S')
    backup.mkdir(parents=True, exist_ok=False)
    (backup / args.source.name).write_text(original)
    args.source.write_text(changed)
    (backup / 'manifest.json').write_text(json.dumps({
        'source': str(args.source), 'before_sha256': hashlib.sha256(original.encode()).hexdigest(),
        'after_sha256': hashlib.sha256(changed.encode()).hexdigest(),
        'boot_arg': 'marble_graphics_services=1', 'max_lines': 192,
        'behavior_change': 'bounded diagnostic output only',
    }, indent=2) + '\n')
    print(f'Applied; backup {backup}')


if __name__ == '__main__':
    main()
