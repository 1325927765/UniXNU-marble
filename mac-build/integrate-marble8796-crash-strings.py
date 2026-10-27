"""Add a QEMU-gated, filtered heap-string scan for iOS bring-up crashes."""
from pathlib import Path
import sys

source = (Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else
          Path.home() / "unixnu-marble8796-build/xnu/osfmk/kern/exception.c")
text = source.read_text()
marker = "/* MARBLE_CRASH_STRING_SCAN */"
if marker in text:
    raise SystemExit("crash-string scan is already installed")

decl = "void marble_crash_log(const char *name, int pid, int sig, uint64_t code, uint64_t subcode);\n"
assert text.count(decl) == 1
text = text.replace(decl, decl + "static void marble_crash_strings(const char *name);\n", 1)

call = "\tprintf(\"%s\\n\", line);\n}\n#endif /* ARM64_BOARD_CONFIG_MARBLE */"
assert text.count(call) == 1
text = text.replace(call, "\tprintf(\"%s\\n\", line);\n"
    "\tif (((sig == 6 && strcmp(name, \"backboardd\") == 0) ||\n"
    "\t    (sig == 5 && strcmp(name, \"watchdogd\") == 0)) &&\n"
    "\t\tint scan = 0;\n"
    "\t\tif (PE_parse_boot_argn(\"marble_crash_scan\", &scan, sizeof(scan)) && scan) {\n"
    "\t\t\tmarble_crash_strings(name);\n"
    "\t\t}\n"
    "\t}\n}\n\n"
    "/* MARBLE_CRASH_STRING_SCAN */\n"
    "static void\n"
    "marble_crash_strings(const char *name)\n"
    "{\n"
    "\tvm_map_t map = current_map();\n"
    "\tvm_map_offset_t addr = 0;\n"
    "\tuint64_t scanned = 0;\n"
    "\tunsigned int lines = 0;\n"
    "\tchar *buf = kalloc_data(65536, Z_WAITOK);\n"
    "\tif (buf == NULL) return;\n"
    "\tprintf(\"MARBLE STR scan %s\\n\", name);\n"
    "\twhile (lines < 96 && scanned < (96ull << 20)) {\n"
    "\t\tvm_map_size_t size = 0;\n"
    "\t\tnatural_t depth = 0;\n"
    "\t\tvm_region_submap_info_data_64_t info;\n"
    "\t\tmach_msg_type_number_t count = VM_REGION_SUBMAP_INFO_V2_COUNT_64;\n"
    "\t\tif (vm_map_region_recurse_64(map, &addr, &size, &depth,\n"
    "\t\t    (vm_region_submap_info_64_t)&info, &count) != KERN_SUCCESS) break;\n"
    "\t\tvm_map_offset_t base = addr;\n"
    "\t\taddr += size;\n"
    "\t\tif (info.is_submap || (info.protection & (VM_PROT_READ | VM_PROT_WRITE)) !=\n"
    "\t\t    (VM_PROT_READ | VM_PROT_WRITE) || info.user_tag < 1 || info.user_tag > 11) continue;\n"
    "\t\tfor (vm_map_offset_t off = 0; off < size && lines < 96; off += 65536) {\n"
    "\t\t\tsize_t len = (size - off) < 65536 ? (size_t)(size - off) : 65536;\n"
    "\t\t\tif (copyin((user_addr_t)(base + off), buf, len) != 0) continue;\n"
    "\t\t\tscanned += len;\n"
    "\t\t\tsize_t start = 0;\n"
    "\t\t\tfor (size_t i = 0; i <= len; i++) {\n"
    "\t\t\t\tbool ok = i < len && (unsigned char)buf[i] >= 0x20 && (unsigned char)buf[i] < 0x7f;\n"
    "\t\t\t\tif (ok) continue;\n"
    "\t\t\t\tsize_t run = i - start;\n"
    "\t\t\t\tif (run >= 16) {\n"
    "\t\t\t\t\tchar s[192];\n"
    "\t\t\t\t\tsize_t n = run < sizeof(s) - 1 ? run : sizeof(s) - 1;\n"
    "\t\t\t\t\tmemcpy(s, buf + start, n); s[n] = 0;\n"
    "\t\t\t\t\tif (strnstr(s, \"exception\", n) || strnstr(s, \"Exception\", n) ||\n"
    "\t\t\t\t\t    strnstr(s, \"reason\", n) || strnstr(s, \"nil\", n) || strnstr(s, \"failed\", n) ||\n"
    "\t\t\t\t\t    strnstr(s, \"Failed\", n) || strnstr(s, \"Error\", n) ||\n"
    "\t\t\t\t\t    strnstr(s, \"container\", n) || strnstr(s, \"watchdog\", n) ||\n"
    "\t\t\t\t\t    strnstr(s, \"IOService\", n) || strnstr(s, \"kext\", n) ||\n"
    "\t\t\t\t\t    strnstr(s, \"discover\", n) || strnstr(s, \"open\", n)) {\n"
    "\t\t\t\t\t\tprintf(\"MARBLE STR %s\\n\", s); lines++;\n"
    "\t\t\t\t\t}\n"
    "\t\t\t\t}\n"
    "\t\t\t\tstart = i + 1;\n"
    "\t\t\t}\n"
    "\t\t}\n"
    "\t}\n"
    "\tprintf(\"MARBLE STR done %llu KiB %u lines\\n\", scanned >> 10, lines);\n"
    "\tkfree_data(buf, 65536);\n"
    "}\n"
    "#endif /* ARM64_BOARD_CONFIG_MARBLE */", 1)
source.write_text(text)
print(f"installed filtered backboardd heap scan in {source}")
