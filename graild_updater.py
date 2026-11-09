"""Separate, network-free updater. Only installs publisher-signed app binaries."""
import argparse
from contextlib import contextmanager
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

from app_version import APP_VERSION
from update_trust import TRUSTED_PUBLIC_KEYS
from update_security import (UpdateError, atomic_json, strict_json, validated_job,
                             verify_manifest, verify_file, sha256_file, update_root)


def kernel():
    api = ctypes.WinDLL("kernel32", use_last_error=True)
    api.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    api.OpenProcess.restype = wintypes.HANDLE
    api.CloseHandle.argtypes = [wintypes.HANDLE]
    api.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    api.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    api.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    api.CreateMutexW.restype = wintypes.HANDLE
    api.ReleaseMutex.argtypes = [wintypes.HANDLE]
    return api


@contextmanager
def install_lock(target):
    if os.name != "nt":
        raise UpdateError("The installer is supported on Windows only.")
    api = kernel()
    name = "Local\\GRAILD-Update-" + hashlib.sha256(str(target).casefold().encode()).hexdigest()
    handle = api.CreateMutexW(None, False, name)
    if not handle:
        raise UpdateError("Could not lock the installation.")
    acquired = api.WaitForSingleObject(handle, 0) in (0, 128)
    try:
        if not acquired:
            raise UpdateError("Another GRAIL'D update is already running.")
        yield
    finally:
        if acquired:
            api.ReleaseMutex(handle)
        api.CloseHandle(handle)


class ParentProcess:
    def __init__(self, pid, target):
        self.api = kernel()
        self.handle = self.api.OpenProcess(0x00100000 | 0x1000, False, int(pid))
        if not self.handle:
            raise UpdateError("GRAIL'D exited before the updater was ready. Reopen it and retry.")
        length = wintypes.DWORD(32768)
        buffer = ctypes.create_unicode_buffer(length.value)
        if not self.api.QueryFullProcessImageNameW(self.handle, 0, buffer, ctypes.byref(length)) or os.path.normcase(os.path.realpath(buffer.value)) != os.path.normcase(str(target)):
            self.close()
            raise UpdateError("Updater parent process does not match the target executable.")

    def wait(self):
        if self.api.WaitForSingleObject(self.handle, 180000) != 0:
            raise UpdateError("GRAIL'D is still running. No files were replaced.")

    def close(self):
        if self.handle:
            self.api.CloseHandle(self.handle)
            self.handle = None


def independent_environment():
    environment = {key: value for key, value in os.environ.items() if not key.startswith("_PYI_")}
    environment["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    return environment


def launch(command):
    # PyInstaller changes the DLL search path; do not leak its bundle into a new EXE.
    if os.name == "nt":
        ctypes.windll.kernel32.SetDllDirectoryW(None)
    try:
        return subprocess.Popen(command, env=independent_environment(),
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), close_fds=True)
    finally:
        if os.name == "nt" and hasattr(sys, "_MEIPASS"):
            ctypes.windll.kernel32.SetDllDirectoryW(sys._MEIPASS)


def replace_when_unlocked(source, target, seconds=30):
    deadline = time.monotonic() + seconds
    while True:
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if time.monotonic() >= deadline:
                raise UpdateError("The executable is still locked. Close other copies of GRAIL'D and retry.") from None
            time.sleep(0.25)


def copy_new(source, destination):
    with open(source, "rb") as incoming, open(destination, "xb") as outgoing:
        shutil.copyfileobj(incoming, outgoing, length=1024 * 1024)
        outgoing.flush()
        os.fsync(outgoing.fileno())


def stop_launched_process(process):
    if process.poll() is not None:
        return
    if os.name == "nt":
        system_directory = ctypes.create_unicode_buffer(32768)
        length = ctypes.windll.kernel32.GetSystemDirectoryW(system_directory, len(system_directory))
        if not length or length >= len(system_directory):
            raise UpdateError("Could not resolve the Windows system directory to stop the updated app.")
        taskkill = (Path(system_directory.value) / "taskkill.exe").resolve(strict=True)
        if taskkill.name.casefold() != "taskkill.exe" or not taskkill.is_file():
            raise UpdateError("Could not resolve the trusted Windows taskkill utility.")
        subprocess.run([str(taskkill), "/PID", str(process.pid), "/T", "/F"], shell=False, capture_output=True,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), timeout=30)
    else:
        process.terminate()
    process.wait(timeout=30)


@contextmanager
def executable_handle(path, writable=False, timeout=30):
    if os.name != "nt":
        yield
        return
    api = kernel()
    api.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                               wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    api.CreateFileW.restype = wintypes.HANDLE
    deadline = time.monotonic() + timeout
    # A write lease cannot coexist with a running executable image. It also
    # prevents another process from starting the old image during backup.
    access = 0x40000000 if writable else 0x80000000
    sharing = (0x1 | 0x4) if writable else 0x1
    handle = None
    while True:
        handle = api.CreateFileW(str(path), access, sharing, None, 3, 0x80, None)
        if handle and handle != ctypes.c_void_p(-1).value:
            break
        if time.monotonic() >= deadline:
            raise UpdateError("The executable is in use or cannot be locked safely. Close other app copies and retry.")
        time.sleep(0.25)
    try:
        yield
    finally:
        api.CloseHandle(handle)


def monitor_startup(target, job, token, version):
    # Hold the verified target read-only across process creation, preventing
    # modification between the final hash check and Windows loading the image.
    request = strict_json((job / "request.json").read_bytes())
    manifest = verify_manifest(strict_json((job / "manifest.json").read_bytes()), TRUSTED_PUBLIC_KEYS,
                               request["repository"], request["channel"], request["current_version"])
    with executable_handle(target):
        verify_file(target, manifest)
        process = launch([str(target), "--post-update", str(job), token])
    try:
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            health = job / "health.json"
            if health.is_file():
                try:
                    data = strict_json(health.read_bytes())
                    if isinstance(data, dict) and data.get("token") == token:
                        if data.get("version") != version:
                            raise UpdateError("The new executable reported the wrong application version.")
                        if process.poll() in (None, 0):
                            return
                except OSError:
                    pass
            if process.poll() is not None:
                raise UpdateError("The new build exited before its startup health check passed.")
            time.sleep(0.25)
        raise UpdateError("The new build did not pass its startup health check in time.")
    except Exception:
        stop_launched_process(process)
        raise


def read_request(job, keys):
    request = strict_json((job / "request.json").read_bytes())
    if request.get("current_version") != APP_VERSION:
        raise UpdateError("This updater does not match the running app version.")
    manifest = verify_manifest(strict_json((job / "manifest.json").read_bytes()), keys,
                               request["repository"], request["channel"], request["current_version"])
    raw_target = Path(request["target"])
    target = raw_target.resolve()
    data = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / "JuiceSpot"
    if not raw_target.is_absolute() or raw_target.is_symlink() or target.suffix.lower() != ".exe" or target.is_relative_to(data.resolve()) or target.is_relative_to(update_root().resolve()):
        raise UpdateError("Invalid installation target. User data cannot be an installation directory.")
    if not isinstance(request.get("health_token"), str) or len(request["health_token"]) != 64:
        raise UpdateError("Invalid update health token.")
    if not isinstance(request.get("old_sha256"), str) or len(request["old_sha256"]) != 64:
        raise UpdateError("Missing original executable checksum.")
    return request, manifest, target


def rollback(target, backup, old_digest):
    if not backup.is_file() or sha256_file(backup) != old_digest:
        raise UpdateError("The recovery backup failed verification. It was not executed.")
    replace_when_unlocked(backup, target)
    if sha256_file(target) != old_digest:
        raise UpdateError("The restored executable failed verification.")


def install_job(directory, keys=TRUSTED_PUBLIC_KEYS, parent_factory=ParentProcess, startup=monitor_startup):
    job = validated_job(directory)
    request, manifest, target = read_request(job, keys)
    payload = job / "payload.exe"
    verify_file(payload, manifest)
    backup = target.parent / (".graild-backup-" + job.name + ".exe")
    incoming = target.parent / (".graild-new-" + job.name + ".exe")
    committed = False
    parent = None
    with install_lock(target):
        try:
            if not target.is_file() or sha256_file(target) != request["old_sha256"]:
                raise UpdateError("The installed executable changed. No update was installed.")
            parent = parent_factory(request["parent_pid"], target)
            atomic_json(job / "ready.json", {"ready": True})
            parent.wait()
            parent.close()
            parent = None
            # Verify independently again after the original app has exited.
            verify_file(payload, manifest)
            if sha256_file(target) != request["old_sha256"]:
                raise UpdateError("The original executable changed during shutdown.")
            atomic_json(job / "journal.json", {"phase": "preparing", "version": manifest["version"]})
            copy_new(payload, incoming)
            verify_file(incoming, manifest)
            with executable_handle(target, writable=True):
                copy_new(target, backup)
                if sha256_file(backup) != request["old_sha256"]:
                    raise UpdateError("Could not verify the recovery backup.")
                atomic_json(job / "journal.json", {"phase": "prepared", "version": manifest["version"]})
            # MoveFileEx cannot replace a destination while our own write handle
            # is open. Release it here; Windows still refuses a running image.
            replace_when_unlocked(incoming, target)
            committed = True
            atomic_json(job / "journal.json", {"phase": "installed", "version": manifest["version"]})
            verify_file(target, manifest)
            startup(target, job, request["health_token"], manifest["version"])
            atomic_json(job / "journal.json", {"phase": "healthy", "version": manifest["version"]})
            atomic_json(job / "result.json", {"status": "installed", "version": manifest["version"], "message": "Update installed and startup verified."})
        except Exception as error:
            if committed:
                try:
                    rollback(target, backup, request["old_sha256"])
                    atomic_json(job / "journal.json", {"phase": "rolled_back", "version": manifest["version"]})
                    atomic_json(job / "result.json", {"status": "rolled_back", "message": str(error) + " The previous build was restored."})
                    launch([str(target)])
                except Exception as recovery_error:
                    atomic_json(job / "result.json", {"status": "recovery_required", "message": str(recovery_error), "backup": str(backup)})
            else:
                atomic_json(job / "result.json", {"status": "failed", "message": str(error)})
            raise
        finally:
            if parent:
                parent.close()
            if incoming.exists():
                incoming.unlink()


def recover_job(directory, keys=TRUSTED_PUBLIC_KEYS):
    job = validated_job(directory)
    request, manifest, target = read_request(job, keys)
    backup = target.parent / (".graild-backup-" + job.name + ".exe")
    with install_lock(target):
        current = sha256_file(target) if target.is_file() else ""
        if current == request["old_sha256"]:
            atomic_json(job / "result.json", {"status": "rolled_back", "message": "The previous build is already installed."})
            return
        if current and current != manifest["sha256"]:
            raise UpdateError("The installation changed independently; recovery will not overwrite it.")
        rollback(target, backup, request["old_sha256"])
        atomic_json(job / "journal.json", {"phase": "rolled_back", "version": manifest["version"]})
        atomic_json(job / "result.json", {"status": "rolled_back", "message": "Interrupted update recovered. The previous build is restored."})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job", required=True)
    parser.add_argument("--recover", action="store_true")
    args = parser.parse_args()
    try:
        if args.recover:
            recover_job(args.job)
        else:
            install_job(args.job)
        return 0
    except Exception as error:
        try:
            job = validated_job(args.job)
            if not (job / "result.json").exists():
                atomic_json(job / "result.json", {"status": "failed", "message": str(error)})
        except Exception:
            pass
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
