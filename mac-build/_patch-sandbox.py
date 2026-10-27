#!/usr/bin/env python3
"""QEMU-only permissive MAC policy named Sandbox, after sweet patch 0050."""
from pathlib import Path

path = Path.home() / "unixnu-marble8796-build/xnu/bsd/kern/marble_amfi.c"
text = path.read_text()
if "mpc_name = \"Sandbox\"" in text:
    print("already present")
    raise SystemExit(0)

old_inc = "#include <sys/codesign.h>\n"
new_inc = "#include <sys/codesign.h>\n#include <sys/errno.h>\n"
if old_inc not in text:
    raise SystemExit("include anchor missing")
text = text.replace(old_inc, new_inc, 1)

old = """static const struct mac_policy_ops marble_amfi_mac_ops = {
	.mpo_vnode_check_signature = marble_amfi_vnode_check_signature,
};
"""
new = r"""/*
 * Policy "Sandbox": libsystem_sandbox calls __mac_syscall("Sandbox", op, arg).
 * Without a policy of that name every call fails with ENOPOLICY and launchd
 * reports mach lookups as "error = 159: Sandbox restriction" (backboardd never
 * reaches mobilegestalt or iohideventsystem). This QEMU stand-in is not Apple's
 * sandbox: checks and profile init succeed; operations that must return a
 * container path or extension token fail with ENOENT. The first use of each
 * operation number is logged. Do not ship this on hardware.
 */
static uint64_t marble_sandbox_seen;

static int
marble_sandbox_syscall(struct proc *p, int call, __unused user_addr_t arg)
{
	if (call >= 0 && call < 64 && !(marble_sandbox_seen & (1ULL << call))) {
		marble_sandbox_seen |= 1ULL << call;
		char name[32];
		proc_name(proc_pid(p), name, sizeof(name));
		printf("MARBLE Sandbox: %s op %d\n", name, call);
	}
	switch (call) {
	case 4:         /* container path (audit token / pid) */
	case 5:         /* extension issue */
	case 6:         /* extension consume */
	case 0x43:      /* container expected */
		return ENOENT;
	default:
		return 0;
	}
}

static const struct mac_policy_ops marble_amfi_mac_ops = {
	.mpo_vnode_check_signature = marble_amfi_vnode_check_signature,
};

static const struct mac_policy_ops marble_sandbox_mac_ops = {
	.mpo_policy_syscall = marble_sandbox_syscall,
};

static struct mac_policy_conf marble_sandbox_mac_conf = {
	.mpc_name = "Sandbox",
	.mpc_fullname = "MARBLE permissive sandbox stand-in",
	.mpc_ops = &marble_sandbox_mac_ops,
};

static mac_policy_handle_t marble_sandbox_mac_handle;
"""
if old not in text:
    raise SystemExit("ops anchor missing")
text = text.replace(old, new, 1)

old_reg = """	printf("MARBLE AMFI: platform binary policy %s (%d)\\n",
	    error ? "NOT registered" : "registered", error);
}
"""
new_reg = """	printf("MARBLE AMFI: platform binary policy %s (%d)\\n",
	    error ? "NOT registered" : "registered", error);
	error = mac_policy_register(&marble_sandbox_mac_conf, &marble_sandbox_mac_handle, NULL);
	printf("MARBLE Sandbox: permissive policy %s (%d)\\n",
	    error ? "NOT registered" : "registered", error);
}
"""
if old_reg not in text:
    raise SystemExit("register anchor missing")
text = text.replace(old_reg, new_reg, 1)
path.write_text(text)
print("patched", path)
