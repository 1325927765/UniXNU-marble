from pathlib import Path
import re
import sys

p = Path(sys.argv[1]) / 'iokit/Kernel/arm/MarbleFramebuffer.cpp'
s = p.read_text()
start_marker = 'IOReturn\nAppleCLCD::newUserClient('
end_marker = 'bool\nAppleCLCD::start(IOService *provider)'
start = s.index(start_marker)
end = s.index(end_marker, start)
replacement = r'''IOReturn
AppleCLCD::newUserClient(task_t owningTask, void *securityID, UInt32 type,
    OSDictionary *properties, IOUserClient **handler)
{
    char name[MAXCOMLEN + 1] = { 0 };
    proc_t proc = (proc_t)get_bsdtask_info(owningTask);
    int pid = proc != NULL ? proc_pid(proc) : -1;
    if (pid >= 0) {
        proc_name(pid, name, sizeof(name));
    }
    IOLog("MARBLE FB: newUserClient %s[%d] request type %u\n", name, pid, type);
    IOReturn result = IOService::newUserClient(owningTask, securityID, type, properties, handler);
    IOLog("MARBLE FB: newUserClient %s[%d] result %d handler %p\n", name, pid, result,
        handler != NULL ? *handler : NULL);
    return result;
}
'''
s = s[:start] + replacement + '\n' + s[end:]
decl = '\tIOReturn newUserClient(task_t owningTask, void *securityID, UInt32 type,\n\t    OSDictionary *properties, IOUserClient **handler) APPLE_KEXT_OVERRIDE;\n'
if s.count(decl) == 2:
    first = s.index(decl)
    s = s[:first] + s[first + len(decl):]
elif s.count(decl) != 1:
    raise RuntimeError('expected one or two duplicate declarations')
p.write_text(s)
