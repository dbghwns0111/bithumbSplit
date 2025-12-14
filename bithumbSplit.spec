# bithumbSplit.spec
# -*- mode: python ; coding: utf-8 -*-
block_cipher = None

a = Analysis(
    ['gui/gui_app.py'],
    pathex=['.'],
    binaries=[],
    datas=[
        ('.env', '.'),
        ('config/tick_table.py', 'config'),
        ('api/api.py', 'api'),
        ('utils/telegram.py', 'utils'),
        ('strategy/auto_trade.py', 'strategy'),
        ('shared/state.py', 'shared'),
    ],
    hiddenimports=[
        'strategy.auto_trade',
        'api.api',
        'config.tick_table',
        'utils.telegram',
        'shared.state',
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='bithumbSplit',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    icon="images/bithumbSplit.png"
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='bithumbSplit'
)
