# PocketPaw Desktop Launcher — PyInstaller Spec
# Builds a lightweight .exe/.app that bootstraps pocketpaw installation.
# Created: 2026-02-10
#
# Usage:
#   pip install pyinstaller pystray Pillow
#   pyinstaller installer/launcher/build/launcher.spec
#
# Output: dist/PocketPaw/ (folder mode for fast startup)

import platform
from pathlib import Path

# Paths
# SPECPATH is provided by PyInstaller and points to the directory containing this spec file
ROOT_DIR = Path(SPECPATH).parent.parent.parent  # Go up to repo root
LAUNCHER_DIR = ROOT_DIR / "installer" / "launcher"
ASSETS_DIR = LAUNCHER_DIR / "assets"

# Collect data files (icon, etc.)
datas = []
if (ASSETS_DIR / "icon.png").exists():
    datas.append((str(ASSETS_DIR / "icon.png"), "launcher/assets"))

# Platform-specific settings
if platform.system() == "Windows":
    icon_file = str(ASSETS_DIR / "icon.ico") if (ASSETS_DIR / "icon.ico").exists() else None
    console = False  # No console window on Windows
elif platform.system() == "Darwin":
    icon_file = str(ASSETS_DIR / "icon.icns") if (ASSETS_DIR / "icon.icns").exists() else None
    console = False
else:
    icon_file = None
    console = True  # Linux: keep console for debugging

a = Analysis(
    [str(LAUNCHER_DIR / "__main__.py")],
    pathex=[str(LAUNCHER_DIR.parent), "."],
    datas=datas,
    hiddenimports=[
        "pystray",
        "pystray._darwin" if platform.system() == "Darwin" else "pystray._win32" if platform.system() == "Windows" else "pystray._xorg",
        "PIL",
        "PIL.Image",
        "tkinter",
        "tkinter.ttk",
        # Launcher modules — both package paths so PyInstaller collects them
        "launcher",
        "launcher.__init__",
        "launcher.__main__",
        "launcher.bootstrap",
        "launcher.server",
        "launcher.tray",
        "launcher.splash",
        "launcher.updater",
    ],
    excludes=[
        # Don't bundle heavy stuff — pocketpaw goes in the venv, not here
        "numpy",
        "pandas",
        "torch",
        "tensorflow",
        "anthropic",
        "openai",
        "playwright",
        "fastapi",
        "uvicorn",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data)

exe = EXE(
    pyz,
    a.scripts,
    [],  # Not one-file mode
    exclude_binaries=True,
    name="PocketPaw",
    debug=False,
    strip=False,
    upx=True,
    console=console,
    icon=icon_file,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    name="PocketPaw",
)

# macOS: Create .app bundle
if platform.system() == "Darwin":
    app = BUNDLE(
        coll,
        name="PocketPaw.app",
        icon=icon_file,
        bundle_identifier="com.pocketpaw.launcher",
        info_plist={
            "CFBundleName": "PocketPaw",
            "CFBundleDisplayName": "PocketPaw",
            "CFBundleVersion": "0.1.0",
            "CFBundleShortVersionString": "0.1.0",
            "LSBackgroundOnly": False,
            "LSUIElement": True,  # Hide from Dock, show in menu bar
            "NSHighResolutionCapable": True,
        },
    )
