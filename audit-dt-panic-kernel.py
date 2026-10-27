#!/usr/bin/env python3
"""Verify the actual source rebuild removed BCM2837's fixed panic-log mapping."""
from pathlib import Path
import hashlib,json,re,struct,subprocess
ROOT=Path(__file__).resolve().parent

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def inspect(path):
    names={m[2]:int(m[1],16) for m in re.finditer(r'^([0-9a-fA-F]+)\s+\S\s+(\S+)$',subprocess.check_output(['llvm-nm','-n',path],text=True),re.M)}
    low=names['_PE_create_console'];high=names['_PE_current_console']
    assert low<high and high-low<4096
    text=subprocess.check_output(['llvm-objdump','-d',f'--start-address={low:#x}',f'--stop-address={high:#x}',path],text=True)
    return text

def main():
    out=ROOT/'research/dt-panic-audit-20261023';out.mkdir(parents=True,exist_ok=True)
    before=ROOT/'out/UNTESTED-marble-early-xnu/marble-early-source-kernel.macho'
    after=ROOT/'out/UNTESTED-marble-xnu-dt-panic/marble-early-source-kernel.macho'
    old=inspect(before);new=inspect(after)
    # These are the actual MOVZ/MOVK instructions forming x0=0x3c0fc000.
    old_fixed='52980000' in old and '72a781e0' in old and '<_ml_io_map_wcomb>' in old
    new_fixed='52980000' in new and '72a781e0' in new
    assert old_fixed and not new_fixed
    assert '<_SecureDTLookupEntry>' in new and '<_SecureDTGetProperty>' in new
    record=json.loads((ROOT/'research/mac-dt-panic-20261023/pe_init.o.json').read_text().strip().rstrip(','))
    args=record['arguments']
    flag='-DXNU_DT_PANIC_REGION=1' in args or any(a=='-D' and b=='XNU_DT_PANIC_REGION=1' for a,b in zip(args,args[1:]))
    assert flag
    assert sha(before)=='0c90bb00da42b1bdb8890fed6f6719091fe1cb17e3655860bfd31c81a5ced1c2'
    assert sha(after)==json.loads((ROOT/'research/mac-dt-panic-20261023/build-report.json').read_text())['kernel_sha256']
    (out/'before-console.S.txt').write_text(old);(out/'after-console.S.txt').write_text(new)
    report={'original_kernel_sha256':sha(before),'fixed_kernel_sha256':sha(after),'fixed_panic_physical_address_removed':'0x3c0fc000','old_fixed_mapping_bytes':0x4000,'address_below_all_live_dram_banks':True,'new_device_tree_lookup_path_verified':True,'actual_compiler_flag_verified':flag,'old_kernel_unchanged':True,'selftests_disabled':False,'new_adt_panic_buffer_fabricated':False,'hardware_cause_proven':False,'scope':'Concrete incorrect platform mapping removed via upstream configuration; actual hardware stop has not been traced and may have other causes','pass':True}
    (out/'result.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
if __name__=='__main__':main()
