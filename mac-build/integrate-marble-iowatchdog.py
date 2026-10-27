"""Add a Marble-only IOWatchdog service needed by stock iOS watchdogd."""
from pathlib import Path
import sys

root = Path(sys.argv[1]).expanduser().resolve()
tables = root / "iokit/KernelConfigTables.cpp"
files = root / "iokit/conf/files.arm64"
impl = root / "iokit/Kernel/arm/MarbleWatchdog.cpp"

table_text = tables.read_text()
needle = '''    "   {"\n    "     'IOClass'         = IOCoreSurfaceRoot;'''
replacement = '''    "   {"\n    "     'IOClass'         = IOWatchdog;"\n    "     'IOProviderClass' = IOResources;"\n    "     'IOMatchCategory' = IOWatchdog;"\n    "   },"\n    "   {"\n    "     'IOClass'         = IOCoreSurfaceRoot;'''
assert table_text.count(needle) == 1, "unexpected Marble IOKit table"
table_text = table_text.replace(needle, replacement, 1)

files_text = files.read_text()
entry = "iokit/Kernel/arm/MarbleWatchdog.cpp                              optional iokitcpp\n"
if entry not in files_text:
    anchor = "iokit/Kernel/arm/MarbleFramebuffer.cpp"
    line = next((line for line in files_text.splitlines(keepends=True) if anchor in line), None)
    assert line, "Marble IOKit source list anchor missing"
    files_text = files_text.replace(line, line + entry, 1)

source = r'''/* Marble-only software IOWatchdog endpoint for QEMU bring-up. */
#include <pexpert/arm64/board_config.h>
#if defined(ARM64_BOARD_CONFIG_MARBLE)
#include <IOKit/IOService.h>
#include <IOKit/IOUserClient.h>
#include <IOKit/IOKitKeys.h>
#include <IOKit/IOLib.h>
#include <IOKit/IOMemoryDescriptor.h>

class IOWatchdog : public IOService {
    OSDeclareDefaultStructors(IOWatchdog);
public:
    bool start(IOService *provider) APPLE_KEXT_OVERRIDE;
    IOReturn setProperties(OSObject *properties) APPLE_KEXT_OVERRIDE;
};
OSDefineMetaClassAndStructors(IOWatchdog, IOService);

IOReturn IOWatchdog::setProperties(__unused OSObject *properties)
{
    return kIOReturnSuccess;
}

bool IOWatchdog::start(IOService *provider)
{
    if (!IOService::start(provider)) return false;
    setProperty(kIOUserClientClassKey, "IOWatchdogUserClient");
    setProperty("IOPMUPrimary", 1ULL, 32);
    registerService();
    IOLog("MARBLE WDT: IOWatchdog registered\\n");
    return true;
}

class IOWatchdogUserClient : public IOUserClient {
    OSDeclareDefaultStructors(IOWatchdogUserClient);
public:
    IOReturn clientClose(void) APPLE_KEXT_OVERRIDE;
    IOReturn externalMethod(uint32_t, IOExternalMethodArguments *,
        IOExternalMethodDispatch *, OSObject *, void *) APPLE_KEXT_OVERRIDE;
};
OSDefineMetaClassAndStructors(IOWatchdogUserClient, IOUserClient);

IOReturn IOWatchdogUserClient::clientClose(void)
{
    terminate();
    return kIOReturnSuccess;
}

IOReturn IOWatchdogUserClient::externalMethod(uint32_t selector,
    IOExternalMethodArguments *args, __unused IOExternalMethodDispatch *dispatch,
    __unused OSObject *target, __unused void *reference)
{
    for (uint32_t i = 0; i < args->scalarOutputCount; i++) args->scalarOutput[i] = 0;
    if (args->structureOutputDescriptor != NULL) {
        IOByteCount len = args->structureOutputDescriptor->getLength();
        const uint64_t zero = 0;
        for (IOByteCount off = 0; off < len; off += sizeof(zero)) {
            args->structureOutputDescriptor->writeBytes(off, &zero,
                len - off < sizeof(zero) ? len - off : sizeof(zero));
        }
    } else if (args->structureOutput != NULL) {
        bzero(args->structureOutput, args->structureOutputSize);
    }
    IOLog("MARBLE WDT: selector %u accepted\\n", selector);
    return kIOReturnSuccess;
}
#endif /* ARM64_BOARD_CONFIG_MARBLE */
'''

if impl.exists():
    raise SystemExit(f"refusing to overwrite existing {impl}")
tables.write_text(table_text)
files.write_text(files_text)
impl.write_text(source)
print("installed Marble-only IOWatchdog service")
