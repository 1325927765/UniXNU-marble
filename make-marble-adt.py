#!/usr/bin/env python3
"""Derive a single-core early XNU ADT from the actual marble Linux FDT."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import struct
import zlib


def iphone_x_product():
    """Copy the matching restore DT's product traits, excluding syscfg slots.

    These describe the iPhone userspace compatibility profile. F5 hardware
    addresses and device drivers still come exclusively from its measured FDT.
    """
    root = Path(__file__).resolve().parent
    path = root / 'research/iphone16-restore-input/d22ap.adt'
    spec = importlib.util.spec_from_file_location('apple_adt', root / 'research/reference-ios-sweet/tools/adt.py')
    codec = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(codec)
    data = path.read_bytes()
    tree, consumed = codec.parse(data)
    if consumed != len(data) or tree.prop('model') != b'iPhone10,3\0':
        raise ValueError('Expected complete iPhone X D22AP restore device tree')
    product = next(child for child in tree.children if child.name == 'product')
    props = [(key, value) for key, flags, value in product.props
             if not flags and key not in ('name', 'AAPL,phandle')]
    required = {'artwork-device-idiom': b'phone\0',
                'artwork-scale-factor': struct.pack('<I', 3),
                'artwork-device-subtype': struct.pack('<I', 2436)}
    if any(dict(props).get(key) != value for key, value in required.items()):
        raise ValueError('D22AP artwork classification differs from expected iPhone X')
    return props


def read_fdt(data):
    magic, total, start, strings, _, version, _, bootcpu, slen, length = struct.unpack_from('>10I', data)
    if magic != 0xd00dfeed or version != 17 or total != len(data) or strings+slen > total or start+length > total:
        raise ValueError('Unsupported FDT header')
    nodes, stack = {}, []
    cursor = start
    while cursor < start+length:
        tag, = struct.unpack_from('>I', data, cursor)
        cursor += 4
        if tag == 1:
            end = data.index(b'\0', cursor, start+length)
            stack.append(data[cursor:end].decode())
            path = '/' + '/'.join(stack[1:])
            if path in nodes: raise ValueError('Duplicate FDT path')
            nodes[path] = {}
            cursor = (end+4) & ~3
        elif tag == 2:
            if not stack: raise ValueError('Unbalanced FDT')
            stack.pop()
        elif tag == 3:
            size, key = struct.unpack_from('>II', data, cursor)
            cursor += 8
            if not stack or key >= slen or cursor+size > start+length: raise ValueError('Invalid FDT property')
            end = data.index(b'\0', strings+key, strings+slen)
            name = data[strings+key:end].decode()
            props = nodes['/' + '/'.join(stack[1:])]
            if name in props: raise ValueError('Duplicate FDT property')
            props[name] = data[cursor:cursor+size]
            cursor = (cursor+size+3) & ~3
        elif tag == 9:
            if stack: raise ValueError('Unbalanced FDT end')
            return nodes, bootcpu
        elif tag != 4:
            raise ValueError('Unknown FDT token')
    raise ValueError('FDT end missing')


def node(name, properties=(), children=()):
    properties = [('name', name.encode()+b'\0'), *properties]
    encoded = struct.pack('<II', len(properties), len(children))
    for key, value in properties:
        if len(key.encode()) >= 32: raise ValueError('ADT property name too long')
        encoded += struct.pack('<32sI', key.encode(), len(value)) + value + bytes(-len(value)%4)
    return encoded+b''.join(children)


def nvram():
    # Fresh volatile CHRP snapshot, using the upstream IODTNVRAM bank ABI.
    def header(name, size):
        raw = bytearray(struct.pack('<BBH12s', 0x70, 0, size//16, name))
        checksum = sum(raw)
        while checksum > 255: checksum = (checksum & 255)+(checksum >> 8)
        raw[1] = checksum
        return raw
    data = bytearray(8192)
    data[:16] = header(b'nvram',32)
    data[32:48] = header(b'common',2064)
    data[2096:2112] = header(b'free',8192-2096)
    struct.pack_into('<I',data,16,zlib.adler32(data[20:]))
    return [('nvram-bank-size',struct.pack('<I',8192)),('nvram-bank-count',struct.pack('<I',1)),
            ('nvram-current-bank',bytes(4)),('nvram-proxy-data',bytes(data))]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fdt',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--ramdisk',action='store_true',help='Reserve a RAMDisk property for DarwinBoot to populate from initrd')
    parser.add_argument('--xnu8796-gic', action='store_true', help='Use the 8796 GIC binding and marble boot-CPU driver match')
    parser.add_argument('--allow-unrestricted-fs', action='store_true', help='Explicit development CSR filesystem policy for the converted HFS shared cache')
    parser.add_argument('--no-effaceable-storage', action='store_true', help='Describe the custom device without Apple effaceable storage; use the existing development keybag plist')
    parser.add_argument('--boot-framebuffer-display', action='store_true', help='Match the built-in AppleCLCD service to the actual bootloader GOP framebuffer; no physical address in this node')
    parser.add_argument('--synthetic-platform-uuid', action='store_true', help='Supply fixed lab identity inputs for IOPlatformUUID; not an Apple device identity')
    parser.add_argument('--iphone-x-ui', action='store_true', help='Select iPhone X userspace UI identity and no-Home-button layout; retain measured F5 hardware nodes')
    parser.add_argument('--ufs-probe-node',action='store_true',
                        help='Add the measured marble UFS host registers to ADT for an explicitly read-only XNU probe')
    args = parser.parse_args()
    raw = args.fdt.read_bytes()
    dt, bootcpu = read_fdt(raw)
    if b'SM7475' not in dt['/']['model'] or bootcpu != 0:
        parser.error('Requires actual marble SM7475 FDT with boot CPU affinity 0')
    regs = struct.unpack('>4I',dt['/soc/interrupt-controller@17100000']['reg'])
    stride, = struct.unpack('>Q',dt['/soc/interrupt-controller@17100000']['redistributor-stride'])
    timer, = struct.unpack('>I',dt['/soc/timer']['clock-frequency'])
    cpu, = struct.unpack('>Q',dt['/cpus/cpu@0']['reg'])
    method = dt['/soc/psci']['method']
    if regs != (0x17100000,0x10000,0x17180000,0x200000) or stride != 0x40000 or timer != 19200000 or cpu != 0 or method != b'smc\0':
        parser.error('Actual marble resources differ from the qualified source/diagnostic inputs')
    memory = dt['/memory']['reg']
    if len(memory)%16: parser.error('Unexpected memory reg ABI')
    banks = list(struct.iter_unpack('>QQ',memory))
    banks.sort()
    if any(not size or base+size >= 1<<64 for base,size in banks): parser.error('Invalid DRAM bank')
    if any(a+n>b for (a,n),(b,_) in zip(banks,banks[1:])): parser.error('Overlapping DRAM banks')
    low, high = min(base for base,_ in banks), max(base+size for base,size in banks)
    base, dsize, rbase, rsize = regs
    timer_interrupts=struct.unpack('>12I',dt['/soc/timer']['interrupts'])
    if timer_interrupts[6:8] != (1,11):
        parser.error('Expected measured virtual timer PPI 11 / INTID 27')
    gic_name='gic' if args.xnu8796_gic else 'intc'
    gic_properties=[('compatible',b'arm,gic-v3\0'),('reg',struct.pack('<4Q',0,dsize,rbase-base,rsize)),
                    ('redistributor-stride',struct.pack('<I' if args.xnu8796_gic else '<Q',stride))]
    if args.xnu8796_gic:
        gic_properties += [('interrupt-controller',b''),('virtual-timer-intid',struct.pack('<I',27))]
    boot_cpu_compatible=dt['/cpus/cpu@0']['compatible']
    if args.xnu8796_gic:
        # Local IOKit personality binds MarbleCPU to this marker. Keep the
        # measured CPU compatibility as the fallback; this is a driver match.
        boot_cpu_compatible=b'marble,boot-cpu\0'+boot_cpu_compatible
    chosen_children=[node('memory-map',[('RAMDisk',bytes(16))] if args.ramdisk else [])]
    if args.allow_unrestricted_fs:
        chosen_children.append(node('asmb',[('lp-sip0',struct.pack('<Q',0x2)),('lp-sip1',struct.pack('<I',0))]))
    bus_size = max(base+dsize,rbase+rsize)-base
    children=[
        node('chosen',[('random-seed',os.urandom(64)),('darwinboot-memory-size',struct.pack('<Q',0x20000000)),
                       # libimg4 queries this algorithm separately from manifest identity.
                       ('crypto-hash-method',b'sha2-384\0'),
                       # Stable lab values, also used by the existing QEMU helper.
                       # Required by IOPlatformExpertDevice::generatePlatformUUID.
                       *([('unique-chip-id',struct.pack('<Q',0x4D4152424C450001)),
                          ('chip-id',struct.pack('<I',0x8015))] if args.synthetic_platform_uuid else []),
                       # Physical DRAM address envelope, not installed RAM or allocator extent.
                       # Only DarwinBoot's independently allocated window enters boot_args.memorySize.
                       ('dram-base',struct.pack('<Q',low)),('dram-size',struct.pack('<Q',high-low)),
                       *([('display-scale',struct.pack('<I',3))] if args.boot_framebuffer_display else []),*nvram()],
             chosen_children),
        node('cpus',children=[node('cpu0',[('state',b'running\0'),('device_type',b'cpu\0'),
                ('reg',struct.pack('<I',cpu)),('compatible',boot_cpu_compatible),
                ('timebase-frequency',struct.pack('<I',timer))])]),
        node('psci',[('compatible',b'arm,psci-1.0\0'),('method',method)]),
        node('defaults',[('no-effaceable-storage',struct.pack('<I',1))] if args.no_effaceable_storage else []),node('options'),
        node('product',iphone_x_product() if args.iphone_x_ui else
             [('product-name',b'POCO F5\0'),('model',b'xiaomi,marble\0')]),
        node('arm-io',[('device_type',b'soc\0'),('ranges',struct.pack('<3Q',0,base,bus_size))],[
            node(gic_name,gic_properties),
            *([node('disp0',[('compatible',b'marble,display\0'),
                            ('device_type',b'display-subsystem\0'),
                            ('canvas-width',struct.pack('<I',1125)),
                            ('canvas-height',struct.pack('<I',2436))])]
              if args.boot_framebuffer_display else [])]),
    ]
    ufs_report=None
    if args.ufs_probe_node:
        path='/soc/ufshc@1d84000'
        if path not in dt:
            parser.error('Live FDT has no expected marble UFS host node')
        ufs=dt[path]
        if ufs.get('compatible') != b'qcom,ufshc\0' or ufs.get('status') != b'ok\0':
            parser.error('Live FDT UFS node is not the enabled qcom,ufshc host')
        cells=struct.unpack('>6I',ufs['reg']) if len(ufs.get('reg',b''))==24 else ()
        regions=[(cells[i],cells[i+1]) for i in range(0,len(cells),2)]
        if regions != [(0x1d84000,0x3000),(0x1d88000,0x8000),(0x1d90000,0x9000)]:
            parser.error(f'Live FDT UFS regions differ from the audited marble values: {regions!r}')
        iommu=struct.unpack('>3I',ufs.get('iommus',b'')) if len(ufs.get('iommus',b''))==12 else ()
        if len(iommu)!=3 or iommu[1:] != (0xe0,0):
            parser.error(f'Live FDT UFS IOMMU stream differs from audited SID 0xe0: {iommu!r}')
        # The XNU probe only reads these registers. No DMA descriptors or SCSI
        # commands are enabled by this node; the stream ID is metadata only.
        children.append(node('marble-ufs-probe',[
            ('reg',struct.pack('<QQ',*regions[0])),
            ('marble,stream-id',struct.pack('<I',iommu[1])),
            ('marble,read-only-probe',b'yes\0')]))
        ufs_report={'source_path':path,'regions':[{'base':hex(a),'bytes':s} for a,s in regions],
                    'iommu_stream_id':hex(iommu[1]),'writes_or_dma_enabled':False}
    if args.iphone_x_ui:
        children.append(node('buttons',[
            ('button-names',b'volup\0voldown\0hold\0'),
            ('home-button-type',struct.pack('<I',2)),
            ('opposed-power-vol-buttons',struct.pack('<I',1))]))
    identity = ([('model',b'iPhone10,3\0'),
                 ('compatible',b'D22AP\0iPhone10,3\0xiaomi,marble\0qcom,sm7475\0'),
                 ('target-type',b'D22\0'),('target-sub-type',b'D22AP\0')]
                if args.iphone_x_ui else
                [('model',b'POCO F5\0'),('compatible',b'xiaomi,marble\0qcom,sm7475\0')])
    adt=node('device-tree',identity,children)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_bytes(adt)
    report = {'fdt_sha256':hashlib.sha256(raw).hexdigest(),'adt_sha256':hashlib.sha256(adt).hexdigest(),
              'boot_cpu_affinity':cpu,'timer_hz':timer,'gic_reg':list(map(hex,regs)),
              'gic_redistributor_stride':hex(stride),'psci':'smc','owned_memory_request_bytes':0x20000000,
              'advertised_memory_banks':[{'base':hex(b),'bytes':s} for b,s in banks],
              'dram_address_envelope':{'base':hex(low),'bytes':high-low,'includes_address_gaps':True},
              'memory_note':'DRAM address envelope is not RAM capacity. XNU allocation is confined to a real 512 MiB UEFI-owned window.',
              'ufs_probe_node':ufs_report,'ramdisk_slot':args.ramdisk,
              'hardware_xnu_boot_observed':False,'native_storage_enabled':False,'smp_enabled':False}
    report['xnu8796_gic_binding']=args.xnu8796_gic
    report['gic_node_path']='/arm-io/'+gic_name
    report['gic_redistributor_stride_property_bytes']=4 if args.xnu8796_gic else 8
    report['boot_cpu_driver_match']='marble,boot-cpu' if args.xnu8796_gic else None
    report['development_csr_allow_unrestricted_fs']=args.allow_unrestricted_fs
    report['no_effaceable_storage']=args.no_effaceable_storage
    report['crypto_hash_method']='sha2-384'
    report['synthetic_platform_uuid_inputs']=({'unique-chip-id':'0x4d4152424c450001','chip-id':'0x8015','apple_device_identity':False} if args.synthetic_platform_uuid else None)
    report['boot_framebuffer_display']=args.boot_framebuffer_display
    if args.boot_framebuffer_display:
        report['display_binding']={'path':'/arm-io/disp0','compatible':'marble,display',
            'logical_canvas':[1125,2436],'display_scale':3,
            'physical_framebuffer_source':'PE_current_console from DarwinBoot GOP; no fixed framebuffer address in ADT'}
    args.output.with_suffix('.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))


if __name__ == '__main__': main()
