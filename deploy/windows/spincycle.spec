# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec -- bundles app.py plus the whole app/ directory (copied
# in verbatim, not analyzed by PyInstaller's import graph, since it's
# imported dynamically via sys.path.insert -- see app._app_source_dir())
# into an onedir build at dist/Spin Cycle/.
#
# Run via build.ps1 (handles the venv + icon generation too), or directly
# from an already-set-up venv:
#
#     pyinstaller spincycle.spec --distpath dist --workpath build --noconfirm

a = Analysis(
    ["app.py"],
    pathex=[],
    binaries=[],
    datas=[("../../app", "app")],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Spin Cycle",
    debug=False,
    strip=False,
    upx=False,
    console=False,  # windowed app, no terminal popup
    icon="icon.ico",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="Spin Cycle",
)
