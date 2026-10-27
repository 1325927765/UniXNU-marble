/*
 * Minimal device-tree platform expert for POCO F5 (marble).
 * Uses XNU's normal platform, power-domain and nub initialization. Hardware
 * interrupt and power-management services are supplied by separate drivers.
 */
#include <pexpert/arm64/board_config.h>

#if defined(MARBLE)
#include <IOKit/IOPlatformExpert.h>
#include <IOKit/IODeviceTreeSupport.h>
#include <IOKit/IOLib.h>

class MarblePlatformExpert : public IODTPlatformExpert {
	OSDeclareDefaultStructors(MarblePlatformExpert);

public:
	bool start(IOService *provider) APPLE_KEXT_OVERRIDE;
	void processTopLevel(IORegistryEntry *root) APPLE_KEXT_OVERRIDE;
	const char *deleteList(void) APPLE_KEXT_OVERRIDE;
	const char *excludeList(void) APPLE_KEXT_OVERRIDE;
};

OSDefineMetaClassAndStructors(MarblePlatformExpert, IODTPlatformExpert);

bool
MarblePlatformExpert::start(IOService *provider)
{
	IOLog("MARBLE: starting device-tree platform expert\n");
	if (!IODTPlatformExpert::start(provider)) {
		return false;
	}
	registerService();
	IOLog("MARBLE: platform expert registered\n");
	return true;
}

const char *
MarblePlatformExpert::deleteList(void)
{
	return "()";
}

const char *
MarblePlatformExpert::excludeList(void)
{
	return "('chosen', 'defaults', 'cpus', 'options')";
}

void
MarblePlatformExpert::processTopLevel(IORegistryEntry *root)
{
	/*
	 * The stock implementation requires an Apple NVRAM /options node.
	 * MARBLE has no NVRAM controller; publish real CPU/device nodes without
	 * inventing one. createNubs adds the topology's logical CPU/cluster IDs.
	 */
	IORegistryEntry *cpus = root->childFromPath("cpus", gIODTPlane);
	if (cpus != NULL) {
		createNubs(this, IODTFindMatchingEntries(cpus, kIODTExclusive, NULL));
		cpus->release();
	}
	createNubs(this, IODTFindMatchingEntries(root, kIODTExclusive, excludeList()));

	/* Publish /arm-io children as IOPlatformDevice nubs for built-in drivers. */
	IORegistryEntry *armio = root->childFromPath("arm-io", gIODTPlane);
	if (armio != NULL) {
		createNubs(this, IODTFindMatchingEntries(armio, kIODTExclusive, "('gic')"));
		armio->release();
	}
}




#endif /* MARBLE */
