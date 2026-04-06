# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['monitor_rotator.py'],
    pathex=[],
    binaries=[],
    datas=[('monitor_config.json', '.'), ('db_config.enc', '.'), ('encryption_key.key', '.')],
    hiddenimports=['selenium.webdriver.chrome.webdriver', 'selenium.webdriver.chrome.service', 'selenium.webdriver.chrome.options', 'selenium.webdriver.common.service', 'selenium.webdriver.common.driver_finder', 'selenium.webdriver.remote.webdriver', 'selenium.webdriver.remote.remote_connection', 'selenium.webdriver.common.options', 'selenium.webdriver.chromium.webdriver', 'selenium.webdriver.chromium.service', 'selenium.webdriver.chromium.options', 'selenium.webdriver.chromium.remote_connection'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='MonitorRotator',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
