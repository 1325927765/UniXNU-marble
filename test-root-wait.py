#!/usr/bin/env python3
"""Run the exact live diagnostic to a genuine root-wait log and observe IOLog return."""
import hashlib,json,re,shutil,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent

def main():
    out=ROOT/'out/UNTESTED-marble-xnu-vtimer-wait';kernel=out/'marble-entry-probe-kernel.macho'
    meta=json.loads((out/'kernel-probe.json').read_text());mark=meta['root_wait_marker']
    assert not meta['automatic_reset'] and hashlib.sha256(kernel.read_bytes()).hexdigest()==meta['instrumented_kernel_sha256']
    dest=ROOT/'research/qemu-vtimer-wait-20261023';dest.mkdir(parents=True,exist_ok=True)
    esp=dest/'esp';shutil.copytree(ROOT/'research/qemu-vtimer-timer-20261023/esp',esp,dirs_exist_ok=True)
    shutil.copyfile(kernel,esp/'EFI/UniXNU/Payloads/kernel.macho')
    nm=subprocess.check_output(['llvm-nm','-n',kernel],text=True)
    names={m[2]:int(m[1],16) for m in re.finditer(r'^([0-9a-fA-F]+)\s+\S\s+(\S+)$',nm,re.M)}
    requests={n:f'{names[n]:x}:{size:x}' for n,size in {'_source_corecrypto14_status':4,'_prng_ready':4,'_armcpu_registered':4,'_armcpu_gic_ready':4,'_armcpu_timer_interrupts':8}.items()}
    command=[sys.executable,ROOT/'sources/UniXNU/scripts/qemu-entry/gdb-stop.py',mark['original_IOLog_va'],
             '--entry-register-equals','0:'+mark['message_va'],'--finish-function','--fixture',dest,'--esp',esp,
             '--kernel',kernel,'--firmware','/usr/share/AAVMF/AAVMF_CODE.fd','--system-registers',
             '--gic-version','3','--qemu-ramfb','--capture-screen','--timeout','90',
             '--trace-address',hex(names['_bsd_init']),'--trace-address',hex(names['_IOFindBSDRoot'])]
    message_request=f'{int(mark["message_va"],16):x}:{len(mark["log_message"].encode())+1:x}'
    command+=['--read-memory',message_request]
    for request in requests.values():command+=['--read-memory',request]
    with (dest/'observer.log').open('w') as log:subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,check=True)
    g=json.loads((dest/'gdb-stop.json').read_text());uart=(dest/'gdb-uart.log').read_text(errors='replace')
    values={n:int.from_bytes(bytes.fromhex(g['memory'][req]),'little') for n,req in requests.items()}
    returned=g['function_return_stack_matched'] and int(g['pc'],16)==int(mark['hook_call_va'],16)+4
    actual_message=bytes.fromhex(g['memory'][message_request])
    actual_call=int(g['function_entry_arguments'][0],16)==int(mark['message_va'],16) and actual_message==mark['log_message'].encode()+b'\0'
    valid=returned and actual_call and values['_source_corecrypto14_status']==0 and values['_prng_ready']==1 and values['_armcpu_gic_ready']==1 and values['_armcpu_timer_interrupts']>0
    report={'kernel_sha256':meta['instrumented_kernel_sha256'],'genuine_root_wait_log_observed':actual_call,'serial_log_text_observed':mark['log_message'].strip() in uart,'root_message_read_from_guest':actual_message.rstrip(b'\0').decode(),
            'original_IOLog_return_observed':returned,'normal_automatic_reset':False,'globals':values,
            'root_filesystem_mounted':False,'scope':'Exact live diagnostic in QEMU; selected actual root-wait IOLog by message pointer, then observed original IOLog return with matching stack. No phone evidence.',
            'screen_visual_review_required':True,'pass':bool(valid)}
    (dest/'result.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2));assert valid

if __name__=='__main__':main()
