"""Check distribution identity and test the non-editable wheel in a fresh environment."""
from __future__ import annotations
import argparse
from email.parser import BytesParser
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import tomllib
import venv
import zipfile


def metadata_identity(raw, name, version):
    data=BytesParser().parsebytes(raw)
    if data.get_all('Name') != [name] or data.get_all('Version') != [version]:
        raise ValueError('distribution metadata name/version is ambiguous or mismatched')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('wheel',type=Path)
    parser.add_argument('sdist',type=Path)
    parser.add_argument('--report',type=Path,required=True)
    args=parser.parse_args()
    wheel,sdist=args.wheel.resolve(strict=True),args.sdist.resolve(strict=True)
    env={k:v for k,v in os.environ.items() if k not in {'PYTHONPATH','PYTHONHOME'}}
    env['PYTHONNOUSERSITE']='1'
    with tempfile.TemporaryDirectory(prefix='worldstate-installed-') as directory:
        root=Path(directory);source=root/'source';source.mkdir()
        with tarfile.open(sdist) as archive:
            members=archive.getmembers()
            if len(members)>10000 or sum(m.size for m in members)>50*1024*1024 or len({m.name for m in members})!=len(members):
                raise ValueError('invalid or excessive source archive')
            archive.extractall(source,filter='data')
        roots=list(source.iterdir())
        if len(roots)!=1 or not roots[0].is_dir():raise ValueError('expected one source root')
        project=roots[0]
        project_metadata=tomllib.loads((project/'pyproject.toml').read_text(encoding='utf-8'))['project']
        name,version=project_metadata['name'],project_metadata['version']
        metadata_identity((project/'PKG-INFO').read_bytes(),name,version)
        package=project/'src/worldstate_check'
        reference={'worldstate_check/'+p.relative_to(package).as_posix():p.read_bytes() for p in package.rglob('*.py')}
        with zipfile.ZipFile(wheel) as archive:
            names=archive.namelist()
            if len(set(names))!=len(names):raise ValueError('duplicate wheel members')
            metadata=[n for n in names if n.endswith('.dist-info/METADATA')]
            if len(metadata)!=1:raise ValueError('ambiguous wheel metadata')
            metadata_identity(archive.read(metadata[0]),name,version)
            actual={n:archive.read(n) for n in names if n.startswith('worldstate_check/') and n.endswith('.py')}
            if actual!=reference:raise ValueError('wheel/source runtime mismatch')
        environment=root/'venv';venv.EnvBuilder(with_pip=True).create(environment)
        python=environment/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
        home=root/'synthetic-home';home.mkdir();env.update(HOME=str(home),USERPROFILE=str(home))
        def run(argv):subprocess.run([str(python),*argv],cwd=project,env=env,check=True,timeout=180)
        run(['-m','pip','install','--disable-pip-version-check',str(wheel),'pytest>=8,<10'])
        run(['-m','pip','check'])
        run(['-c','import pathlib,sys,worldstate_check as w,importlib.metadata as m; p=pathlib.Path(w.__file__).resolve().parent; assert pathlib.Path(sys.prefix).resolve() in p.parents; assert w.__version__==m.version(sys.argv[1])==sys.argv[2]; source=pathlib.Path("src/worldstate_check"); assert {f.relative_to(source).as_posix():f.read_bytes() for f in source.rglob("*.py")}=={f.relative_to(p).as_posix():f.read_bytes() for f in p.rglob("*.py")}; print("Installed source matches",p)',name,version])
        run(['-m','pytest','-o','addopts=','-q'])
        run(['scripts/showcase.py','--out',str(root/'showcase')])
        run(['-m','worldstate_check','demo','--scenario','verified'])
        run(['-m','worldstate_check','verify','examples/field-maintenance.yaml'])
        report={'status':'PASS','distribution':name,'version':version,'runtime_modules_matched':len(reference),
                'installation':'fresh non-editable wheel outside checkout',
                'runtime_dependencies':project_metadata['dependencies'],
                'wheel_sha256':hashlib.sha256(wheel.read_bytes()).hexdigest(),
                'sdist_sha256':hashlib.sha256(sdist.read_bytes()).hexdigest()}
    args.report.parent.mkdir(parents=True,exist_ok=True)
    args.report.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
