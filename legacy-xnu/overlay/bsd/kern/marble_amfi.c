/*
 * Built-in AMFI interface for MARBLE.
 *
 * On Apple platforms AppleMobileFileIntegrity registers this interface and
 * provides entitlements through the closed CoreEntitlements library. MARBLE
 * has neither, and code signing reaches it on every exec (ubc_cs_blob_add).
 *
 * Entitlements: when a code signature is added, its XML entitlements blob
 * (already checked against the code directory) is parsed into a
 * MarbleEntitlements object (iokit/Kernel/arm/MarbleEntitlements.cpp), set as
 * the blob's csb_entitlements, and every query is answered from it. DER-only
 * signatures get none. Code signature and page hash validation stay with the
 * kernel. Trust caches remain unavailable (no Image4), so the TrustCache
 * interface is left at version 0.
 *
 * Platform binaries: AMFI marks binaries whose cdhash is in a trust cache
 * as platform binaries from its vnode_check_signature MAC hook. Without
 * trust caches, the MARBLE policy below marks only exact pinned iOS CDHash/type entries on the readonly root
 * filesystem instead (the iOS system binaries are ad-hoc signed and are
 * platform binaries only through the static trust cache).
 *
 * Interfaces no kernel path uses on MARBLE (they serve other Apple kexts)
 * panic with a clear message instead of being NULL.
 */
#if defined(ARM64_BOARD_CONFIG_MARBLE)
#include <kern/debug.h>
#include <kern/startup.h>
#include <pexpert/pexpert.h>
#include <libkern/amfi/amfi.h>
#include <mach/kern_return.h>
#include <sys/codesign.h>
#include <sys/errno.h>
#include <sys/mount.h>
#include <sys/proc.h>
#include <sys/systm.h>
#include <sys/ubc_internal.h>
#include <sys/vnode.h>
#include <security/mac_policy.h>
#include "marble_ios16_cdhashes.inc"

/* iokit/Kernel/arm/MarbleEntitlements.cpp */
void *marble_entitlements_create(const CS_GenericBlob *blob, size_t blob_len);
void *marble_entitlements_copy_dict(const void *ent);
bool marble_entitlements_copy_xml(const void *ent, CS_GenericBlob **out);
bool marble_entitlements_bool(const void *ent, const char *name);
bool marble_entitlements_string(const void *ent, const char *name, const char *value);
void *marble_entitlements_copy_object(const void *ent, const char *name);
unsigned int marble_entitlements_count(const void *ent);
extern void osobject_release(void *object);

/* boot-arg marble_amfi_debug=1: log the entitlements attached to each signature. */
static TUNABLE(uint32_t, marble_amfi_debug, "marble_amfi_debug", 0);

/* The entitlements object of a process's main binary, or NULL. */
static void *
marble_proc_entitlements(proc_t proc)
{
	struct cs_blob *blob = csproc_get_blob(proc);
	return blob != NULL ? csblob_os_entitlements_get(blob) : NULL;
}

static void
marble_amfi_entitlements_invalidate(__unused void *os_entitlements)
{
	/* Queries already require a valid signature (csblob_get_entitlements). */
}

static void *
marble_amfi_entitlements_as_dict(void *os_entitlements)
{
	return marble_entitlements_copy_dict(os_entitlements);
}

static CEError_t
marble_amfi_entitlements_query(__unused void *os_entitlements,
    __unused uint8_t cdhash[CS_CDHASH_LEN], __unused CEQuery_t query,
    __unused size_t query_length)
{
	panic("MARBLE AMFI: CoreEntitlements queries are not implemented");
}

static bool
marble_amfi_entitlements_get_transmuted(__unused void *os_entitlements,
    __unused const CS_GenericBlob **blob)
{
	return false;
}

static bool
marble_amfi_entitlements_get_xml(void *os_entitlements, CS_GenericBlob **blob)
{
	return marble_entitlements_copy_xml(os_entitlements, blob);
}

static bool
marble_amfi_get_legacy_profile_exemptions(__unused const uint8_t **profile,
    __unused size_t *profile_length)
{
	return false;
}

static bool
marble_amfi_get_udid(__unused const uint8_t **udid, __unused size_t *udid_length)
{
	return false;
}

static void *
marble_amfi_query_context_to_object(__unused CEQueryContext_t ctx)
{
	panic("MARBLE AMFI: CoreEntitlements query contexts are not implemented");
}

static kern_return_t
marble_amfi_adjust_with_monitor(__unused void *os_entitlements,
    __unused const CEQueryContext_t ce_ctx, __unused const void *monitor_sig_obj,
    __unused const char *identity, __unused const uint32_t code_signing_flags)
{
	/* MARBLE has no code signing monitor. */
	return KERN_NOT_SUPPORTED;
}

/*
 * Attach the parsed XML entitlements to a code signature being added. This
 * must happen in the vnode_check_signature MAC hook, like AMFI does: later,
 * converting a 4K-page signature to multilevel hashes drops the XML blob.
 * Nothing is granted when the blob is missing, unreadable or does not match
 * its code directory hash.
 */
static void
marble_amfi_attach_entitlements(struct cs_blob *code_signing_blob)
{
	void *xml = NULL;
	size_t xml_len = 0;

	if (csblob_get_entitlements(code_signing_blob, &xml, &xml_len) != 0) {
		printf("MARBLE AMFI: %s: entitlements do not match the code directory, granting none\n",
		    csblob_get_identity(code_signing_blob));
		return;
	}
	if (xml == NULL) {
		return;                 /* no XML entitlements */
	}
	void *ent = marble_entitlements_create(xml, xml_len);
	if (ent == NULL) {
		printf("MARBLE AMFI: %s: unreadable entitlements (%zu bytes), granting none\n",
		    csblob_get_identity(code_signing_blob), xml_len);
		return;
	}
	if (marble_amfi_debug) {
		/* The test keys only exist in tools/mkinit.py test signatures. */
		printf("MARBLE AMFI: %s: %u entitlements (test: bool %d string %d array %d)\n",
		    csblob_get_identity(code_signing_blob), marble_entitlements_count(ent),
		    marble_entitlements_bool(ent, "com.apple.private.marble.test-bool"),
		    marble_entitlements_string(ent, "com.apple.private.marble.test-string", "hello"),
		    marble_entitlements_string(ent, "com.apple.private.marble.test-array", "two"));
	}
	csblob_os_entitlements_set(code_signing_blob, ent);    /* takes a reference */
	osobject_release(ent);
}

static kern_return_t
marble_amfi_adjust_without_monitor(__unused void *os_entitlements,
    __unused struct cs_blob *code_signing_blob)
{
	/* Entitlements were attached in marble_amfi_vnode_check_signature. */
	return KERN_SUCCESS;
}

static kern_return_t
marble_amfi_query_boolean(const void *os_entitlements, const char *entitlement_name)
{
	return marble_entitlements_bool(os_entitlements, entitlement_name) ? KERN_SUCCESS : KERN_DENIED;
}

static kern_return_t
marble_amfi_query_boolean_with_proc(const proc_t proc, const char *entitlement_name)
{
	return marble_amfi_query_boolean(marble_proc_entitlements(proc), entitlement_name);
}

static kern_return_t
marble_amfi_query_string(const void *os_entitlements,
    const char *entitlement_name, const char *entitlement_value)
{
	return marble_entitlements_string(os_entitlements, entitlement_name, entitlement_value) ?
	       KERN_SUCCESS : KERN_DENIED;
}

static kern_return_t
marble_amfi_query_string_with_proc(const proc_t proc,
    const char *entitlement_name, const char *entitlement_value)
{
	return marble_amfi_query_string(marble_proc_entitlements(proc), entitlement_name,
	           entitlement_value);
}

static kern_return_t
marble_amfi_copy_object(const void *os_entitlements,
    const char *entitlement_name, void **entitlement_object)
{
	void *obj = marble_entitlements_copy_object(os_entitlements, entitlement_name);
	if (entitlement_object) {
		*entitlement_object = obj;
	} else if (obj) {
		osobject_release(obj);
	}
	return obj ? KERN_SUCCESS : KERN_NOT_FOUND;
}

static kern_return_t
marble_amfi_copy_object_with_proc(const proc_t proc,
    const char *entitlement_name, void **entitlement_object)
{
	return marble_amfi_copy_object(marble_proc_entitlements(proc), entitlement_name,
	           entitlement_object);
}

static const amfi_t marble_amfi = {
	.OSEntitlements_invalidate = marble_amfi_entitlements_invalidate,
	.OSEntitlements_asdict = marble_amfi_entitlements_as_dict,
	.OSEntitlements_query = marble_amfi_entitlements_query,
	.OSEntitlements_get_transmuted = marble_amfi_entitlements_get_transmuted,
	.OSEntitlements_get_xml = marble_amfi_entitlements_get_xml,
	/* CoreEntitlements is only used by the PMAP_CS code signing monitor. */
	.get_legacy_profile_exemptions = marble_amfi_get_legacy_profile_exemptions,
	.get_udid = marble_amfi_get_udid,
	.query_context_to_object = marble_amfi_query_context_to_object,
	/* .TrustCache stays version 0: trust caches are unavailable without Image4. */
	.OSEntitlements = {
		.version = OSENTITLEMENTS_INTERFACE_VERSION,
		.adjustContextWithMonitor = marble_amfi_adjust_with_monitor,
		.adjustContextWithoutMonitor = marble_amfi_adjust_without_monitor,
		.queryEntitlementBoolean = marble_amfi_query_boolean,
		.queryEntitlementBooleanWithProc = marble_amfi_query_boolean_with_proc,
		.queryEntitlementString = marble_amfi_query_string,
		.queryEntitlementStringWithProc = marble_amfi_query_string_with_proc,
		.copyEntitlementAsOSObject = marble_amfi_copy_object,
		.copyEntitlementAsOSObjectWithProc = marble_amfi_copy_object_with_proc,
	},
};

__startup_func
static void
marble_amfi_register(void)
{
	amfi_interface_register(&marble_amfi);
	printf("MARBLE AMFI: built-in interface registered (XML entitlements)\n");
}
STARTUP(EARLY_BOOT, STARTUP_RANK_MIDDLE, marble_amfi_register);

/*
 * The signature reached this hook validated, so mark it CS_SIGNED like AMFI
 * does: exec copies the flag to the process, and csproc_get_blob() (csops
 * status, cdhash, platform and entitlement queries by process) ignores
 * processes without it. Only pinned iOS CDHash/type entries on the readonly root qualify as a
 * platform binary. New signatures (ubc_cs_blob_add passes its writable copy;
 * revalidation passes the read-only blob itself) get their entitlements here.
 */
static int
marble_amfi_vnode_check_signature(struct vnode *vp, __unused struct label *label,
    __unused cpu_type_t cpu_type, struct cs_blob *cs_blob,
    unsigned int *cs_flags, __unused unsigned int *signer_type,
    __unused int flags, __unused unsigned int platform,
    __unused char **fatal_failure_desc, __unused size_t *fatal_failure_desc_len)
{
	mount_t mp = vnode_mount(vp);
    extern int marble_ufs_root_write_enabled(void);
    int marble_physical_rootrw = mp != NULL &&
        strcmp(vfs_statfs(mp)->f_fstypename,"hfs")==0 &&
        strcmp(vfs_statfs(mp)->f_mntfromname,"/dev/marbleufs0")==0 &&
        marble_ufs_root_write_enabled();

	*cs_flags |= CS_SIGNED;
	uint32_t marble_qemu_writable_root = 0;
	int root_is_readonly = mp != NULL && (vfs_flags(mp) & MNT_RDONLY);
	int qemu_rootrw = PE_parse_boot_argn("marble_qemu_writable_root",
	    &marble_qemu_writable_root, sizeof(marble_qemu_writable_root)) &&
	    marble_qemu_writable_root == 1;
	if (mp != NULL && (vfs_flags(mp) & MNT_ROOTFS) &&
	    (root_is_readonly || qemu_rootrw || marble_physical_rootrw) && marble_ios16_hash_allowed(cs_blob)) {
		*cs_flags |= CS_PLATFORM_BINARY;
	}

    /* Bounded by exec of this one system daemon; does not grant any flags. */
    const char *marble_identity = csblob_get_identity(cs_blob);
    if (marble_identity != NULL && strcmp(marble_identity, "com.apple.webbookmarksd") == 0) {
        printf("MARBLE AMFI APP: webbookmarksd pinned=%d platform=%d root=%d readonly=%d physical_rw=%d\n",
            marble_ios16_hash_allowed(cs_blob), !!(*cs_flags & CS_PLATFORM_BINARY),
            mp != NULL && !!(vfs_flags(mp) & MNT_ROOTFS), root_is_readonly,
            marble_physical_rootrw);
    }
	if (cs_blob != cs_blob->csb_ro_addr && cs_blob->csb_entitlements == NULL) {
		marble_amfi_attach_entitlements(cs_blob);
	}
	return 0;
}

/*
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

static struct mac_policy_conf marble_amfi_mac_conf = {
	.mpc_name = "MARBLE AMFI",
	.mpc_fullname = "MARBLE built-in Mobile File Integrity",
	.mpc_ops = &marble_amfi_mac_ops,
};

static mac_policy_handle_t marble_amfi_mac_handle;

/* Called from bsd_init once MAC policies can register, before any exec. */
void marble_amfi_policy_register(void);

void
marble_amfi_policy_register(void)
{
	int error = mac_policy_register(&marble_amfi_mac_conf, &marble_amfi_mac_handle, NULL);
	printf("MARBLE AMFI: platform binary policy %s (%d)\n",
	    error ? "NOT registered" : "registered", error);
	error = mac_policy_register(&marble_sandbox_mac_conf, &marble_sandbox_mac_handle, NULL);
	printf("MARBLE Sandbox: permissive policy %s (%d)\n",
	    error ? "NOT registered" : "registered", error);
}
#endif /* ARM64_BOARD_CONFIG_MARBLE */
