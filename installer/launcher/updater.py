# PocketPaw Desktop Launcher — Update Checker
# Checks PyPI for newer versions and upgrades the venv install.
# Uses uv when available for faster installs, falls back to pip.
# Created: 2026-02-10

from __future__ import annotations

import json
import logging
import platform
import shutil
import subprocess
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

POCKETCLAW_HOME = Path.home() / ".pocketclaw"
VENV_DIR = POCKETCLAW_HOME / "venv"
UV_DIR = POCKETCLAW_HOME / "uv"
PACKAGE_NAME = "pocketpaw"
PYPI_URL = f"https://pypi.org/pypi/{PACKAGE_NAME}/json"

StatusCallback = Callable[[str], None]


def _noop_status(msg: str) -> None:
    pass


@dataclass
class UpdateInfo:
    """Result of an update check."""

    current_version: str | None = None
    latest_version: str | None = None
    update_available: bool = False
    error: str | None = None


class Updater:
    """Check for and apply PocketPaw updates."""

    def __init__(self, on_status: StatusCallback | None = None) -> None:
        self.on_status = on_status or _noop_status

    def check(self) -> UpdateInfo:
        """Check if a newer version is available on PyPI."""
        info = UpdateInfo()

        # Get current version from venv
        info.current_version = self._get_installed_version()
        if not info.current_version:
            info.error = "PocketPaw not installed"
            return info

        # Get latest version from PyPI
        info.latest_version = self._get_pypi_version()
        if not info.latest_version:
            info.error = "Could not check PyPI for updates"
            return info

        # Compare versions
        info.update_available = self._version_newer(info.latest_version, info.current_version)

        return info

    def apply(self) -> bool:
        """Upgrade pocketpaw in the venv to the latest version."""
        python = self._venv_python()
        if not python.exists():
            self.on_status("PocketPaw not installed")
            return False

        self.on_status("Updating PocketPaw...")

        uv = self._find_uv()
        try:
            if uv:
                logger.info("Running uv pip install --upgrade %s", PACKAGE_NAME)
                # Use overrides file if it exists (created by bootstrap)
                overrides = POCKETCLAW_HOME / "uv-overrides.txt"
                cmd = [uv, "pip", "install", "--upgrade", PACKAGE_NAME,
                       "--python", str(python)]
                if overrides.exists():
                    cmd.extend(["--override", str(overrides)])
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=300,
                )
            else:
                logger.info("Running pip install --upgrade %s", PACKAGE_NAME)
                result = subprocess.run(
                    [str(python), "-m", "pip", "install", "--upgrade",
                     PACKAGE_NAME, "--quiet"],
                    capture_output=True,
                    text=True,
                    timeout=300,
                )
            if result.returncode == 0:
                new_ver = self._get_installed_version()
                self.on_status(f"Updated to v{new_ver}")
                return True
            else:
                logger.error("Update failed: %s", result.stderr[-1000:])
                self.on_status("Update failed. Check logs.")
                return False
        except subprocess.TimeoutExpired:
            self.on_status("Update timed out")
            return False

    # ── Internal ───────────────────────────────────────────────────────

    def _venv_python(self) -> Path:
        if platform.system() == "Windows":
            return VENV_DIR / "Scripts" / "python.exe"
        return VENV_DIR / "bin" / "python"

    def _find_uv(self) -> str | None:
        """Find uv binary (downloaded by bootstrap or on system PATH)."""
        if platform.system() == "Windows":
            local_uv = UV_DIR / "uv.exe"
        else:
            local_uv = UV_DIR / "uv"
        if local_uv.exists():
            return str(local_uv)
        return shutil.which("uv")

    def _get_installed_version(self) -> str | None:
        """Get installed pocketpaw version from venv."""
        python = self._venv_python()
        if not python.exists():
            return None

        uv = self._find_uv()
        try:
            if uv:
                result = subprocess.run(
                    [uv, "pip", "show", PACKAGE_NAME, "--python", str(python)],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
            else:
                result = subprocess.run(
                    [str(python), "-m", "pip", "show", PACKAGE_NAME],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
            if result.returncode == 0:
                for line in result.stdout.splitlines():
                    if line.startswith("Version:"):
                        return line.split(":", 1)[1].strip()
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
        return None

    def _get_pypi_version(self) -> str | None:
        """Fetch the latest version from PyPI JSON API."""
        try:
            req = urllib.request.Request(
                PYPI_URL,
                headers={"Accept": "application/json"},
            )
            resp = urllib.request.urlopen(req, timeout=10)
            data = json.loads(resp.read())
            return data.get("info", {}).get("version")
        except Exception as exc:
            logger.warning("PyPI check failed: %s", exc)
            return None

    def _version_newer(self, latest: str, current: str) -> bool:
        """Compare version strings. Returns True if latest > current."""
        try:
            latest_parts = [int(x) for x in latest.split(".")]
            current_parts = [int(x) for x in current.split(".")]
            return latest_parts > current_parts
        except (ValueError, AttributeError):
            return latest != current
