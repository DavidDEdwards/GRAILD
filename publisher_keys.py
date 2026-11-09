"""Publisher-only key storage. Never imported by the distributed application."""
import csv
import ctypes
from ctypes import wintypes
import getpass
import os
from pathlib import Path
import subprocess

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

HEADER = b"GRAILD-DPAPI-ED25519-v1\n"


class Blob(ctypes.Structure):
    _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_byte))]


def protect(data, decrypt=False):
    if os.name != "nt":
        raise OSError("Windows-protected publisher keys require Windows.")
    crypt = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    buffer = ctypes.create_string_buffer(data)
    incoming = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte)))
    outgoing = Blob()
    if decrypt:
        function = crypt.CryptUnprotectData
        function.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
        ok = function(ctypes.byref(incoming), None, None, None, None, 1, ctypes.byref(outgoing))
    else:
        function = crypt.CryptProtectData
        function.argtypes = [ctypes.POINTER(Blob), wintypes.LPCWSTR, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
        ok = function(ctypes.byref(incoming), "GRAILD publisher signing key", None, None, None, 1, ctypes.byref(outgoing))
    if not ok:
        raise OSError("Windows could not protect or unlock the publisher key for this account.")
    try:
        return ctypes.string_at(outgoing.data, outgoing.size)
    finally:
        kernel.LocalFree.argtypes = [ctypes.c_void_p]
        kernel.LocalFree.restype = ctypes.c_void_p
        kernel.LocalFree(ctypes.cast(outgoing.data, ctypes.c_void_p))


def outside_repository(path):
    path = Path(path).expanduser().resolve()
    if path.is_relative_to(Path(__file__).resolve().parent):
        raise ValueError("Private signing keys must be stored outside the project repository.")
    return path


def restrict_permissions(path):
    if os.name != "nt":
        os.chmod(path, 0o700 if Path(path).is_dir() else 0o600)
        return
    who = subprocess.check_output(['whoami', '/user', '/fo', 'csv', '/nh'], text=True, encoding='utf-8', errors='replace')
    sid = next(csv.reader([who.strip()]))[1]
    if not sid.startswith('S-1-'):
        raise OSError('Could not identify the Windows publisher account.')
    inheritance = '(OI)(CI)' if Path(path).is_dir() else ''
    subprocess.run(['icacls', str(path), '/inheritance:r', '/grant:r', '*'+sid+':'+inheritance+'F', '*S-1-5-18:'+inheritance+'F'],
                   check=True, capture_output=True, creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))


def new_password():
    password = getpass.getpass('Private key password (at least 12 characters): ')
    confirm = getpass.getpass('Confirm password: ')
    if len(password) < 12 or password != confirm:
        raise ValueError('Passwords must match and contain at least 12 characters.')
    return password.encode('utf-8')


def generate_key(filename, windows_protected=False):
    path = outside_repository(filename)
    if path.exists():
        raise FileExistsError('A signing key already exists at that path; it was not replaced.')
    path.parent.mkdir(parents=True, exist_ok=True)
    restrict_permissions(path.parent)
    private = Ed25519PrivateKey.generate()
    if windows_protected:
        secret = private.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())
        content = HEADER + protect(secret)
    else:
        content = private.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.BestAvailableEncryption(new_password()))
    with open(path, 'xb') as file:
        file.write(content)
        file.flush(); os.fsync(file.fileno())
    restrict_permissions(path)
    return private


def load_key(filename):
    content = outside_repository(filename).read_bytes()
    if content.startswith(HEADER):
        return Ed25519PrivateKey.from_private_bytes(protect(content[len(HEADER):], decrypt=True))
    password = getpass.getpass('Release key password: ').encode('utf-8')
    private = serialization.load_pem_private_key(content, password=password)
    if not isinstance(private, Ed25519PrivateKey):
        raise ValueError('The signing key must be Ed25519.')
    return private


def export_encrypted(filename, destination):
    destination = outside_repository(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    restrict_permissions(destination.parent)
    content = load_key(filename).private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.BestAvailableEncryption(new_password()))
    with open(destination, 'xb') as file:
        file.write(content)
    restrict_permissions(destination)
