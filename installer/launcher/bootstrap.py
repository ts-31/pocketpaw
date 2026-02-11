# PocketPaw Desktop Launcher — Bootstrap Module
# Detects Python, creates venv, installs pocketpaw via uv (falls back to pip).
# On Windows, downloads the Python embeddable package if Python is missing.
# Created: 2026-02-10

from __future__ import annotations

import io
import logging
import platform
import shutil
import subprocess
import urllib.request
import venv
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

# Where everything lives
POCKETCLAW_HOME = Path.home() / ".pocketclaw"
VENV_DIR = POCKETCLAW_HOME / "venv"
UV_DIR = POCKETCLAW_HOME / "uv"
EMBEDDED_PYTHON_DIR = POCKETCLAW_HOME / "python"
PACKAGE_NAME = "pocketpaw"
MIN_PYTHON = (3, 11)

# Python embeddable package URL template for Windows
# Format: python-{version}-embed-{arch}.zip
PYTHON_EMBED_VERSION = "3.12.8"
PYTHON_EMBED_URL = "https://www.python.org/ftp/python/{version}/python-{version}-embed-{arch}.zip"

# Dependency overrides — loosen pins from transitive deps that lack
# prebuilt wheels for newer Python versions.
UV_OVERRIDES = [
    "tiktoken>=0.7.0",
]

# uv standalone download URLs
UV_VERSION = "0.6.6"
UV_DOWNLOAD_URLS = {
    ("Windows", "AMD64"): f"https://github.com/astral-sh/uv/releases/download/{UV_VERSION}/uv-x86_64-pc-windows-msvc.zip",
    ("Windows", "x86"): f"https://github.com/astral-sh/uv/releases/download/{UV_VERSION}/uv-i686-pc-windows-msvc.zip",
    ("Darwin", "arm64"): f"https://github.com/astral-sh/uv/releases/download/{UV_VERSION}/uv-aarch64-apple-darwin.tar.gz",
    ("Darwin", "x86_64"): f"https://github.com/astral-sh/uv/releases/download/{UV_VERSION}/uv-x86_64-apple-darwin.tar.gz",
    ("Linux", "x86_64"): f"https://github.com/astral-sh/uv/releases/download/{UV_VERSION}/uv-x86_64-unknown-linux-gnu.tar.gz",
    ("Linux", "aarch64"): f"https://github.com/astral-sh/uv/releases/download/{UV_VERSION}/uv-aarch64-unknown-linux-gnu.tar.gz",
}


@dataclass
class BootstrapStatus:
    """Current state of the bootstrap environment."""

    python_path: str | None = None
    python_version: str | None = None
    venv_exists: bool = False
    pocketpaw_installed: bool = False
    pocketpaw_version: str | None = None
    needs_install: bool = True
    error: str | None = None


ProgressCallback = Callable[[str, int], None]
"""Callback(message, percent_0_to_100)."""


def _noop_progress(msg: str, pct: int) -> None:
    pass


class Bootstrap:
    """Handles Python detection, venv creation, and pocketpaw installation."""

    def __init__(self, progress: ProgressCallback | None = None) -> None:
        self.progress = progress or _noop_progress

    # ── Public API ─────────────────────────────────────────────────────

    def check_status(self) -> BootstrapStatus:
        """Check current environment status without changing anything."""
        status = BootstrapStatus()

        # Find Python
        python = self._find_python()
        if python:
            status.python_path = python
            status.python_version = self._get_python_version(python)

        # Check venv
        venv_python = self._venv_python()
        if venv_python and venv_python.exists():
            status.venv_exists = True
            # Check if pocketpaw is installed in the venv
            uv = self._find_uv()
            version = self._get_installed_version(str(venv_python), uv=uv)
            if version:
                status.pocketpaw_installed = True
                status.pocketpaw_version = version
                status.needs_install = False

        return status

    def run(self, extras: list[str] | None = None) -> BootstrapStatus:
        """Full bootstrap: find/install Python, get uv, create venv, install pocketpaw.

        Args:
            extras: pip extras to install (e.g. ["telegram", "discord"])

        Returns:
            BootstrapStatus with the result.
        """
        status = BootstrapStatus()
        extras = extras or ["recommended"]

        try:
            # Step 1: Find or install Python
            self.progress("Checking Python...", 5)
            python = self._find_python()

            if not python and platform.system() == "Windows":
                self.progress("Downloading Python...", 10)
                python = self._download_embedded_python()

            if not python:
                status.error = (
                    "Python 3.11+ not found. Install from https://www.python.org/downloads/"
                )
                return status

            status.python_path = python
            status.python_version = self._get_python_version(python)
            logger.info("Using Python %s at %s", status.python_version, python)

            # Step 2: Get uv (fast Python package installer)
            self.progress("Setting up uv package manager...", 20)
            uv = self._ensure_uv()
            if not uv:
                logger.warning("Could not get uv, falling back to pip")

            # Step 3: Create venv if needed
            venv_python = self._venv_python()
            if not venv_python or not venv_python.exists():
                self.progress("Creating virtual environment...", 30)
                self._create_venv(python, uv)
                venv_python = self._venv_python()
                if not venv_python or not venv_python.exists():
                    status.error = f"Failed to create venv at {VENV_DIR}"
                    return status

            status.venv_exists = True

            # Step 4: Install pocketpaw
            self.progress("Installing PocketPaw...", 45)
            install_err = self._install_pocketpaw(str(venv_python), extras, uv)
            if install_err:
                status.error = install_err
                return status

            self.progress("Verifying installation...", 90)
            version = self._get_installed_version(str(venv_python), uv)
            if version:
                status.pocketpaw_installed = True
                status.pocketpaw_version = version
                status.needs_install = False
            else:
                status.error = "Installation completed but pocketpaw not found in venv."

            self.progress("Ready!", 100)

        except Exception as exc:
            logger.exception("Bootstrap failed")
            status.error = str(exc)

        return status

    # ── Python Detection ───────────────────────────────────────────────

    def _find_python(self) -> str | None:
        """Find a suitable Python 3.11+ on the system."""
        # Check embedded Python first (Windows)
        embedded = self._embedded_python()
        if embedded and embedded.exists():
            if self._check_python_version(str(embedded)):
                return str(embedded)

        # Check venv Python (already created)
        venv_py = self._venv_python()
        if venv_py and venv_py.exists():
            # Venv exists but we need the base Python to recreate if needed
            pass

        # Check system Python
        candidates = ["python3", "python3.13", "python3.12", "python3.11", "python"]
        for cmd in candidates:
            path = shutil.which(cmd)
            if path and self._check_python_version(path):
                return path

        return None

    def _check_python_version(self, python: str) -> bool:
        """Check if the given Python meets minimum version."""
        try:
            result = subprocess.run(
                [python, "-c", "import sys; print(sys.version_info.major, sys.version_info.minor)"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                parts = result.stdout.strip().split()
                major, minor = int(parts[0]), int(parts[1])
                return (major, minor) >= MIN_PYTHON
        except (subprocess.TimeoutExpired, FileNotFoundError, ValueError, IndexError):
            pass
        return False

    def _get_python_version(self, python: str) -> str | None:
        """Get the full version string."""
        try:
            result = subprocess.run(
                [
                    python,
                    "-c",
                    "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')",
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
        return None

    # ── Embedded Python (Windows) ──────────────────────────────────────

    def _embedded_python(self) -> Path | None:
        """Path to embedded Python executable."""
        if platform.system() != "Windows":
            return None
        return EMBEDDED_PYTHON_DIR / "python.exe"

    def _download_embedded_python(self) -> str | None:
        """Download Python embeddable package for Windows."""
        arch = "amd64" if platform.machine().endswith("64") else "win32"
        url = PYTHON_EMBED_URL.format(version=PYTHON_EMBED_VERSION, arch=arch)

        logger.info("Downloading Python %s from %s", PYTHON_EMBED_VERSION, url)

        try:
            EMBEDDED_PYTHON_DIR.mkdir(parents=True, exist_ok=True)

            self.progress(f"Downloading Python {PYTHON_EMBED_VERSION}...", 15)
            response = urllib.request.urlopen(url, timeout=120)
            data = response.read()

            self.progress("Extracting Python...", 20)
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                zf.extractall(EMBEDDED_PYTHON_DIR)

            # Enable pip in the embedded Python by uncommenting import site
            # in pythonXY._pth file
            pth_files = list(EMBEDDED_PYTHON_DIR.glob("python*._pth"))
            for pth_file in pth_files:
                content = pth_file.read_text()
                content = content.replace("#import site", "import site")
                pth_file.write_text(content)

            # Install pip via get-pip.py (needed as fallback if uv fails)
            self.progress("Installing pip...", 22)
            get_pip_url = "https://bootstrap.pypa.io/get-pip.py"
            get_pip_path = EMBEDDED_PYTHON_DIR / "get-pip.py"
            urllib.request.urlretrieve(get_pip_url, str(get_pip_path))

            python_exe = str(EMBEDDED_PYTHON_DIR / "python.exe")
            subprocess.run(
                [python_exe, str(get_pip_path), "--no-warn-script-location"],
                capture_output=True,
                timeout=120,
            )
            get_pip_path.unlink(missing_ok=True)

            if Path(python_exe).exists():
                logger.info("Embedded Python installed at %s", python_exe)
                return python_exe

        except Exception as exc:
            logger.error("Failed to download embedded Python: %s", exc)

        return None

    # ── uv Package Manager ─────────────────────────────────────────────

    def _uv_path(self) -> Path:
        """Path where we store the uv binary."""
        if platform.system() == "Windows":
            return UV_DIR / "uv.exe"
        return UV_DIR / "uv"

    def _find_uv(self) -> str | None:
        """Find uv on the system or in our download location."""
        # Check our downloaded copy first
        local_uv = self._uv_path()
        if local_uv.exists():
            return str(local_uv)

        # Check system PATH
        system_uv = shutil.which("uv")
        if system_uv:
            return system_uv

        return None

    def _ensure_uv(self) -> str | None:
        """Find or download uv. Returns path to uv binary or None."""
        existing = self._find_uv()
        if existing:
            logger.info("Using uv at %s", existing)
            return existing

        return self._download_uv()

    def _download_uv(self) -> str | None:
        """Download the uv standalone binary."""
        system = platform.system()
        machine = platform.machine()

        # Normalise machine name
        if machine in ("x86_64", "AMD64"):
            machine_key = "AMD64" if system == "Windows" else "x86_64"
        elif machine in ("arm64", "aarch64"):
            machine_key = "arm64" if system == "Darwin" else "aarch64"
        else:
            machine_key = machine

        url = UV_DOWNLOAD_URLS.get((system, machine_key))
        if not url:
            logger.warning("No uv download URL for %s/%s", system, machine)
            return None

        logger.info("Downloading uv from %s", url)
        try:
            UV_DIR.mkdir(parents=True, exist_ok=True)
            response = urllib.request.urlopen(url, timeout=60)
            data = response.read()

            if url.endswith(".zip"):
                with zipfile.ZipFile(io.BytesIO(data)) as zf:
                    # Extract uv.exe from inside the archive
                    for member in zf.namelist():
                        basename = Path(member).name
                        if basename in ("uv.exe", "uv"):
                            target = UV_DIR / basename
                            with zf.open(member) as src, open(target, "wb") as dst:
                                dst.write(src.read())
                            break
            else:
                # .tar.gz
                import tarfile
                with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tf:
                    for member in tf.getmembers():
                        basename = Path(member.name).name
                        if basename == "uv":
                            target = UV_DIR / "uv"
                            with tf.extractfile(member) as src:
                                target.write_bytes(src.read())
                            target.chmod(0o755)
                            break

            uv_bin = self._uv_path()
            if uv_bin.exists():
                logger.info("uv downloaded to %s", uv_bin)
                return str(uv_bin)

        except Exception as exc:
            logger.warning("Failed to download uv: %s", exc)

        return None

    # ── Virtual Environment ────────────────────────────────────────────

    def _venv_python(self) -> Path | None:
        """Path to the Python executable inside the venv."""
        if platform.system() == "Windows":
            return VENV_DIR / "Scripts" / "python.exe"
        return VENV_DIR / "bin" / "python"

    def _create_venv(self, python: str, uv: str | None = None) -> None:
        """Create a virtual environment."""
        logger.info("Creating venv at %s using %s", VENV_DIR, python)
        VENV_DIR.parent.mkdir(parents=True, exist_ok=True)

        if uv:
            # uv venv is much faster
            result = subprocess.run(
                [uv, "venv", str(VENV_DIR), "--python", python, "--quiet"],
                capture_output=True,
                text=True,
                timeout=60,
            )
            if result.returncode == 0:
                return
            logger.warning("uv venv failed (%s), falling back to stdlib", result.stderr.strip())

        # Fallback: use subprocess to call the found Python's venv module
        result = subprocess.run(
            [python, "-m", "venv", str(VENV_DIR), "--clear"],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode != 0:
            # Last resort: try venv.create if we're using the same Python
            logger.warning("subprocess venv failed, trying venv.create: %s", result.stderr)
            venv.create(str(VENV_DIR), with_pip=True, clear=True)

    # ── Package Installation ───────────────────────────────────────────

    def _install_pocketpaw(
        self, venv_python: str, extras: list[str], uv: str | None = None,
    ) -> str | None:
        """Install pocketpaw into the venv with given extras.

        Uses uv if available (10-100x faster), falls back to pip.

        Returns:
            None on success, or an error message string on failure.
        """
        if extras:
            pkg = f"{PACKAGE_NAME}[{','.join(extras)}]"
        else:
            pkg = PACKAGE_NAME

        logger.info("Installing %s (using %s)", pkg, "uv" if uv else "pip")
        self.progress(f"Installing {pkg}...", 50)

        try:
            if uv:
                return self._install_with_uv(uv, venv_python, pkg)
            return self._install_with_pip(venv_python, pkg)
        except subprocess.TimeoutExpired:
            logger.error("Install timed out after 10 minutes")
            return "Installation timed out after 10 minutes. Try again with a faster connection."
        except FileNotFoundError as exc:
            logger.error("Executable not found: %s", exc)
            return f"Executable not found: {exc}"

    def _install_with_uv(self, uv: str, venv_python: str, pkg: str) -> str | None:
        """Install a package using uv pip install with dependency overrides."""
        # Write overrides file so uv can loosen transitive pins
        # (e.g. open-interpreter pins tiktoken==0.7.0 which has no cp313 wheel)
        overrides_file = POCKETCLAW_HOME / "uv-overrides.txt"
        overrides_file.write_text("\n".join(UV_OVERRIDES) + "\n", encoding="utf-8")

        cmd = [uv, "pip", "install", pkg, "--python", venv_python,
               "--override", str(overrides_file)]
        logger.info("Running: %s", " ".join(cmd))

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=600,
        )
        if result.returncode == 0:
            return None  # success

        stderr = result.stderr[-2000:] if result.stderr else ""
        logger.error("uv pip install failed:\n%s", stderr)

        # Retry without overrides in case the override itself caused the issue
        logger.info("Retrying uv pip install without overrides")
        self.progress("Retrying install...", 55)
        result2 = subprocess.run(
            [uv, "pip", "install", pkg, "--python", venv_python],
            capture_output=True,
            text=True,
            timeout=600,
        )
        if result2.returncode == 0:
            return None

        stderr2 = result2.stderr[-2000:] if result2.stderr else ""
        logger.error("uv pip install (no overrides) also failed:\n%s", stderr2)

        # Fallback to pip
        logger.info("Falling back to pip")
        self.progress("Retrying install with pip...", 60)
        return self._install_with_pip(venv_python, pkg)

    def _install_with_pip(self, venv_python: str, pkg: str) -> str | None:
        """Install a package using pip (fallback)."""
        # Make sure pip is up to date first
        subprocess.run(
            [venv_python, "-m", "pip", "install", "--upgrade", "pip", "--quiet"],
            capture_output=True,
            timeout=120,
        )

        result = subprocess.run(
            [venv_python, "-m", "pip", "install", pkg, "--quiet"],
            capture_output=True,
            text=True,
            timeout=600,
        )
        if result.returncode == 0:
            return None  # success

        stderr = result.stderr[-2000:] if result.stderr else ""
        logger.error("pip install failed:\n%s", stderr)
        return self._format_pip_error(stderr)

    @staticmethod
    def _format_pip_error(stderr: str) -> str:
        """Extract a short, actionable message from pip/uv stderr output."""
        for marker in ("ERROR:", "error:", "×"):
            for line in stderr.splitlines():
                stripped = line.strip()
                if stripped.startswith(marker):
                    return f"Install failed: {stripped}"

        return (
            "Failed to install pocketpaw. "
            "Check the log at ~/.pocketclaw/logs/launcher.log for details."
        )

    def _get_installed_version(
        self, venv_python: str, uv: str | None = None,
    ) -> str | None:
        """Get the installed pocketpaw version from the venv."""
        try:
            if uv:
                result = subprocess.run(
                    [uv, "pip", "show", PACKAGE_NAME, "--python", venv_python],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
            else:
                result = subprocess.run(
                    [venv_python, "-m", "pip", "show", PACKAGE_NAME],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
            if result.returncode == 0:
                for line in result.stdout.splitlines():
                    if line.lower().startswith("version:"):
                        return line.split(":", 1)[1].strip()
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
        return None
