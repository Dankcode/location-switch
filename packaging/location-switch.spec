from pathlib import Path
from PyInstaller.utils.hooks import collect_all, collect_submodules, copy_metadata

root = Path(SPECPATH).parent
datas = [(str(root / 'location_switch/static'), 'location_switch/static')]
binaries = []
hiddenimports = collect_submodules('location_switch') + collect_submodules('uvicorn')
for package in ('pymobiledevice3', 'pytcp', 'pytun_pmd3'):
    package_data, package_binaries, package_imports = collect_all(package)
    datas += package_data
    binaries += package_binaries
    hiddenimports += package_imports
datas += copy_metadata('pymobiledevice3', recursive=True)
a = Analysis([str(root / 'packaging/entry.py')], pathex=[str(root)],
             binaries=binaries, datas=datas, hiddenimports=hiddenimports,
             excludes=['pytest', 'IPython', 'tkinter'], noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='LocationSwitch',
          console=True, debug=False, strip=False, upx=False)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='LocationSwitch')
