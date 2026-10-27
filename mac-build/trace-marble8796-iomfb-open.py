"""Trace IOServiceOpen requests reaching AppleCLCD in the QEMU driver."""
from pathlib import Path
import sys

p = Path(sys.argv[1]) / 'iokit/Kernel/arm/MarbleFramebuffer.cpp'
s = p.read_text()
include_anchor = '#include <sys/proc.h>\n'
if s.count(include_anchor) != 1:
    raise RuntimeError('proc include anchor mismatch')
s = s.replace(include_anchor, include_anchor + '#include <kern/task.h>\n', 1)
old = ('\tbool start(IOService *provider) APPLE_KEXT_OVERRIDE;\n'
       '\tvoid addClient(IOMobileFramebufferUserClient *client);\n'
       '\tvoid removeClient(IOMobileFramebufferUserClient *client);\n'
       '\tvoid swap(const uint8_t *rec);\n')
new = (old + '\tIOReturn newUserClient(task_t owningTask, void *securityID, UInt32 type,\n'
       '\t    OSDictionary *properties, IOUserClient **handler) APPLE_KEXT_OVERRIDE;\n')
if s.count(old) != 1:
    raise RuntimeError('AppleCLCD declaration anchor mismatch')
s = s.replace(old, new, 1)
anchor = 'bool\nAppleCLCD::start(IOService *provider)\n'
implementation = '''IOReturn
AppleCLCD::newUserClient(task_t owningTask, void *securityID, UInt32 type,
    OSDictionary *properties, IOUserClient **handler)
{
    char name[MAXCOMLEN + 1] = { 0 };
    int pid = proc_pid(get_bsdtask_info(owningTask));
    proc_name(pid, name, sizeof(name));
    IOLog("MARBLE FB: newUserClient %s[%d] request type %u\\n", name, pid, type);
    IOReturn result = IOService::newUserClient(owningTask, securityID, type, properties, handler);
    IOLog("MARBLE FB: newUserClient %s[%d] result 0x%x handler %p\\n", name, pid, result,
        handler != NULL ? *handler : NULL);
    return result;
}

'''
if s.count(anchor) != 1:
    raise RuntimeError('AppleCLCD implementation anchor mismatch')
p.write_text(s.replace(anchor, implementation + anchor, 1))
