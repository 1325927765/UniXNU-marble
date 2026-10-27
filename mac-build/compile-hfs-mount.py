"""Compile pinned Apple HFS separately using the current XNU C ABI recipe.

An isolated compatibility experiment, not an iOS 16 kernel build or phone boot.
It does not modify the current kernel tree, its archives, or device storage.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import struct
import subprocess

PIN='c475e9e1a63ed00d25d9fbda2903b1ce28912c43' # Apple hfs-650.120.1

def run(*argv,**kw):
    return subprocess.run([str(a) for a in argv],check=True,**kw)

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--tree',type=Path,required=True)
    ap.add_argument('--work',type=Path,required=True)
    ap.add_argument('--reference-patch',type=Path,required=True)
    args=ap.parse_args()
    tree=args.tree.expanduser().resolve(); work=args.work.expanduser().resolve()
    if work.exists(): raise SystemExit('Use a fresh work directory; existing work is preserved')
    work.mkdir(parents=True)
    source=work/'upstream'
    run('git','init','-q',source)
    run('git','-C',source,'fetch','-q','--depth','1','https://github.com/apple-oss-distributions/hfs',PIN)
    run('git','-C',source,'checkout','-q','FETCH_HEAD')
    assert subprocess.check_output(['git','-C',str(source),'rev-parse','HEAD'],text=True).strip()==PIN
    stage=work/'staged'
    for name in ('core','hfs_encodings'): shutil.copytree(source/name,stage/name)
    # This is an unencrypted HFSX mount experiment. Select the upstream desktop
    # feature set (directory hardlinks/encodings), with no AppleKeyStore code.
    config=stage/'core/kext-config.h'
    config_text=config.read_text()
    condition='#if (TARGET_OS_IPHONE && !TARGET_OS_SIMULATOR)'
    assert config_text.count(condition)==1
    config_text=config_text.replace(condition,'#if 0 /* unencrypted HFSX fixture */')
    assert config_text.count('#define QUOTA 1')==1
    config.write_text(config_text.replace('#define QUOTA 1','#define QUOTA 0 /* kernel has no quota support */'))
    encodings=stage/'hfs_encodings/hfs_encodings.h'
    encoding_text=encodings.read_text()
    assert encoding_text.count('#if !TARGET_OS_IPHONE')==1
    encodings.write_text(encoding_text.replace('#if !TARGET_OS_IPHONE',
        '#if 1 /* built-in desktop HFS converter interface */'))
    patch=args.reference_patch.read_text()
    # Reuse only the explicit built-in glue and KPI feature header. Do not apply
    # foreign board patches or register a foreign platform device.
    for name in ('negroni_hfs_compat.h','negroni_hfs_iokit.c'):
        marker='diff --git a/bsd/negroni_hfs/'+name+' '
        section=patch.split(marker,1)[1].split('\ndiff --git ',1)[0]
        text='\n'.join(line[1:] for line in section.splitlines()
                       if line.startswith('+') and not line.startswith('+++'))+'\n'
        text=text.replace('negroni','marble').replace('NEGRONI','MARBLE')
        (stage/name.replace('negroni','marble')).write_text(text.replace('hfs-627.100.6','hfs-650.120.1'))
    header=stage/'core/hfs_iokit.h'; text=header.read_text()
    include='#include <AppleKeyStore/AppleKeyStoreFSServices.h>\n'
    assert text.count(include)==1
    text=text.replace(include,'#if CONFIG_PROTECT\n'+include+'#endif\n')
    i=text.index('int hfs_unwrap_key('); j=text.index('__END_DECLS',i)
    header.write_text(text[:i]+'#if CONFIG_PROTECT\n'+text[i:j]+'#endif\n'+text[j:])
    sdk=Path(subprocess.check_output(['xcrun','--sdk','macosx','--show-sdk-path'],text=True).strip())
    shutil.copyfile(sdk/'usr/include/TargetConditionals.h',stage/'TargetConditionals.h')
    record=json.loads((tree/'build/xnu/ios-obj/DEVELOPMENT_ARM64_BCM2837/bsd/DEVELOPMENT/vfs_conf.o.json').read_text().strip().rstrip(','))
    sources=[stage/line[1:].split()[0].removeprefix('bsd/negroni_hfs/')
             for line in patch.splitlines() if line.startswith('+bsd/negroni_hfs/') and '\toptional' in line]
    sources=[p.with_name(p.name.replace('negroni','marble')) for p in sources]
    out=work/'objects'; out.mkdir()
    failures=[]; objects=[]
    for src in sources:
        dest=out/(src.stem+'.o'); command=[]; a=record['arguments']; k=0
        while k<len(a):
            value=a[k]
            if value==record['file']: command.append(str(src))
            elif value=='-o': command.extend(['-o',str(dest)]); k+=1
            elif value in ('-MF','-MJ'): k+=1
            elif value not in ('-MD','-MP'): command.append(value)
            k+=1
        command+=['-include',str(stage/'marble_hfs_compat.h'),'-I',str(stage),'-I',str(stage/'core')]
        if src.stem in ('hfs_encodinghint','hfs_encodings'):
            command+=['-Dhfs_allocated=hfs_encodings_allocated']
        result=subprocess.run(command,cwd=record['directory'],capture_output=True,text=True)
        (out/(src.stem+'.log')).write_text(result.stdout+result.stderr)
        (out/(src.stem+'.command.json')).write_text(json.dumps(command,indent=2)+'\n')
        if result.returncode:
            failures.append(src.name)
            print('FAIL',src.name,flush=True)
        else:
            assert struct.unpack_from('<4I',dest.read_bytes())==(0xfeedfacf,0x100000c,0,1)
            objects.append(dest)
            print('PASS',src.name,flush=True)
    report={'hfs_source_commit':PIN,'sources':len(sources),'compiled':len(objects),
            'failures':failures,'kernel_linked':False,'filesystem_mounted':False,
            'phone_storage_modified':False,'ios_userspace_booted':False}
    if not failures:
        archive=work/'libMarbleHfs.a'
        run('xcrun','ar','rcs',archive,*objects)
        report['archive_sha256']=hashlib.sha256(archive.read_bytes()).hexdigest()
    (work/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))
    if failures: raise SystemExit(1)

if __name__=='__main__': main()
