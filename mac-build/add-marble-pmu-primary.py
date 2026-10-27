"""Give the Marble watchdog service the PMU role stock watchdogd expects."""
from pathlib import Path
import sys

path = Path(sys.argv[1]).expanduser().resolve()
text = path.read_text()
old = '''public:
    bool start(IOService *provider) APPLE_KEXT_OVERRIDE;
};
OSDefineMetaClassAndStructors(IOWatchdog, IOService);

bool IOWatchdog::start(IOService *provider)
'''
new = '''public:
    bool start(IOService *provider) APPLE_KEXT_OVERRIDE;
    IOReturn setProperties(OSObject *properties) APPLE_KEXT_OVERRIDE;
};
OSDefineMetaClassAndStructors(IOWatchdog, IOService);

IOReturn IOWatchdog::setProperties(__unused OSObject *properties)
{
    return kIOReturnSuccess;
}

bool IOWatchdog::start(IOService *provider)
'''
assert text.count(old) == 1, "unexpected Marble IOWatchdog implementation"
text = text.replace(old, new, 1)
key = '    setProperty(kIOUserClientClassKey, "IOWatchdogUserClient");\n'
assert text.count(key) == 1
text = text.replace(key, key + '    setProperty("IOPMUPrimary", 1ULL, 32);\n', 1)
path.write_text(text)
print("added the IOPMUPrimary role to Marble IOWatchdog")
