# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for LocWarp backend (Python 3.13).
# Build: py -3.13 -m PyInstaller backend/locwarp-backend.spec --noconfirm

from PyInstaller.utils.hooks import collect_all, collect_submodules, copy_metadata

# pymobiledevice3 has a LOT of dynamic imports — collect everything
pmd_datas, pmd_binaries, pmd_hiddenimports = collect_all('pymobiledevice3')

# pytun_pmd3 ships wintun.dll as a data file that ctypes loads at runtime
pytun_datas, pytun_binaries, pytun_hidden = collect_all('pytun_pmd3')

# developer_disk_image is an indirect dependency of pymobiledevice3 (imported
# at the top of services/mobile_image_mounter.py). PyInstaller doesn't pick
# it up via collect_all('pymobiledevice3'), so previously the bundled exe
# would fail to import mobile_image_mounter and silently skip DDI mount.
# That broke iOS <17 users (e.g. iPhone 8 Plus / iOS 16.7) — DtSimulateLocation
# accepts the call but iOS rejects it without DDI.
ddi_datas, ddi_binaries, ddi_hidden = collect_all('developer_disk_image')

# pyimg4 is an indirect dep of mobile_image_mounter's Personalized DDI path.
# pymobiledevice3 calls importlib.metadata.distribution('pyimg4') at import
# time. collect_all('pymobiledevice3') pulls pyimg4's .py files in as
# transitive imports, but NOT its .dist-info metadata directory, so the
# metadata lookup raises PackageNotFoundError and the whole
# mobile_image_mounter import fails. That cascades into "No such service:
# com.apple.instruments.dtservicehub" on iOS 17+ devices whose DDI was never
# pre-mounted by another tool. copy_metadata pulls the dist-info dir into
# the bundle so importlib.metadata finds it. Also collect_all for the
# python files and any companion binaries.
pyimg4_datas, pyimg4_binaries, pyimg4_hidden = collect_all('pyimg4')
pyimg4_meta = copy_metadata('pyimg4')

# apple_compress provides Apple's LZFSE/LZBITMAP codec used by pyimg4's
# Personalized-DDI parse path: mobile_image_mounter -> restore.tss -> restore.img4
# -> ipsw_parser.build_identity -> `from pyimg4 import IM4P` -> pyimg4/parser.py
# `import apple_compress` (the live `else` branch on macOS). apple_compress/__init__.py
# runs `__version__ = version('apple_compress')` at import time, UNGUARDED, so the
# frozen exe raises PackageNotFoundError without the dist-info — the SAME failure mode
# as pyimg4 above. That kills the mobile_image_mounter import -> DDI never mounts ->
# DtSimulateLocation silently no-ops on iOS 17+ (the device accepts the call but iOS
# rejects it without DDI), so route playback fails with "no current position" because
# the teleport's set_location() raised before setting current_position. copy_metadata
# bundles the dist-info (THE fix); collect_all is belt-and-suspenders — apple_compress
# ships no .so (it ctypes-loads the OS libcompression.dylib) but this guarantees all
# submodules ship despite the conditional-branch import.
ac_datas, ac_binaries, ac_hidden = collect_all('apple_compress')
ac_meta = copy_metadata('apple_compress')

# prompt_toolkit is dragged onto the SAME device path by pymobiledevice3:
# mobile_image_mounter -> lockdown -> service_connection.py
# (`from pymobiledevice3.utils import start_ipython_shell` -> bare `import IPython`
# -> IPython terminal -> `from prompt_toolkit...`). prompt_toolkit/__init__.py runs
# `__version__ = metadata.version("prompt_toolkit")` at import time (and asserts pep440
# on it), so the frozen exe raises PackageNotFoundError and the whole mobile_image_mounter
# import dies — same class as apple_compress, one link further down the chain. Only the
# dist-info is missing (the .py is pure-Python, already followed by the Analysis graph
# from the IPython edge), so copy_metadata alone is the fix.
pt_meta = copy_metadata('prompt_toolkit')

# h3 is on the OFFLINE-GEO path (not the location-sim route): timezonefinder requires
# h3>=4 and is imported lazily in services/geo_offline.py. h3/_version.py runs
# `__version__ = metadata.version(__package__)` at import time, unguarded, so the frozen
# exe raises PackageNotFoundError -> timezonefinder import fails -> the offline
# reverse-geocode fallback silently blanks (the `_load_failed` latch). Same metadata-gap
# class; copy_metadata fixes it (h3's Cython .so are followed transitively from the
# static import, so no collect_all needed here).
h3_meta = copy_metadata('h3')

# uvicorn/fastapi also need their sub-modules collected
uvicorn_hidden = collect_submodules('uvicorn')
fastapi_hidden = collect_submodules('fastapi')

# psutil has a Windows-specific extension module that must be bundled
# for NIC enumeration to work in the frozen exe.
ps_datas, ps_binaries, ps_hidden = collect_all('psutil')

# timezonefinder ships its boundary data as package data files and requires
# numpy + h3 (Cython extensions). collect_all grabs timezonefinder's own data
# and hidden submodule imports; PyInstaller's Analysis then follows the static
# h3 import transitively to pull in h3's compiled extensions. numpy is kept
# out of the 'excludes' list below for the same reason.
tzf_datas, tzf_binaries, tzf_hidden = collect_all('timezonefinder')

hidden = [
    *pmd_hiddenimports,
    *pytun_hidden,
    *ddi_hidden,
    *pyimg4_hidden,
    *ac_hidden,
    *uvicorn_hidden,
    *fastapi_hidden,
    *ps_hidden,
    *tzf_hidden,
    'uvicorn.logging',
    'uvicorn.loops',
    'uvicorn.loops.auto',
    'uvicorn.protocols',
    'uvicorn.protocols.http',
    'uvicorn.protocols.http.auto',
    'uvicorn.protocols.websockets',
    'uvicorn.protocols.websockets.auto',
    'uvicorn.lifespan',
    'uvicorn.lifespan.on',
    'websockets',
    'websockets.legacy',
    'websockets.legacy.client',
    'websockets.legacy.server',
    'gpxpy',
    'httpx',
    'multipart',
]

a = Analysis(
    ['main.py'],
    pathex=['.'],
    binaries=[*pmd_binaries, *pytun_binaries, *ddi_binaries, *pyimg4_binaries,
              *ac_binaries, *ps_binaries, *tzf_binaries],
    datas=[*pmd_datas, *pytun_datas, *ddi_datas, *pyimg4_datas, *pyimg4_meta,
           *ac_datas, *ac_meta, *pt_meta, *h3_meta,
           *ps_datas, *tzf_datas,
           ('static/phone.html', 'static'),
           ('static/catalog.json', 'static'),
           ('data/geo', 'data/geo')],
    hiddenimports=hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'matplotlib', 'PIL', 'scipy', 'pandas'],
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='locwarp-backend',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,   # keep console for logs; change to False for prod if desired
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='locwarp-backend',
)
