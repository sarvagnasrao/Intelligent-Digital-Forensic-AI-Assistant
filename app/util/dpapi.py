"""Windows DPAPI helpers for secrets kept on disk.

The per-user config file holds a cloud AI key. Stored as plain text it is
readable by anything running as that Windows account and by anyone who copies
the file. Windows Data Protection encrypts it against the current user with no
extra dependency, so the value in ``config.yaml`` is useless on another account
or machine.

Values are written as ``dpapi:<base64>``. Anything without that prefix is
returned unchanged, which keeps configs written by earlier builds working and
lets the value be replaced the next time settings are saved.
"""
from __future__ import annotations

import base64
import ctypes
import sys
from ctypes import wintypes

PREFIX = "dpapi:"

_CRYPTPROTECT_UI_FORBIDDEN = 0x1


class _DataBlob(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_char)),
    ]


def _to_blob(data: bytes) -> tuple[_DataBlob, ctypes.Array]:
    # The buffer has to outlive the blob, so it is returned to the caller.
    buffer = ctypes.create_string_buffer(data, len(data))
    blob = _DataBlob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))
    return blob, buffer


def _protect(data: bytes) -> bytes:
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    crypt32.CryptProtectData.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]

    in_blob, _buffer = _to_blob(data)
    out_blob = _DataBlob()
    ok = crypt32.CryptProtectData(
        ctypes.byref(in_blob),
        None,
        None,
        None,
        None,
        _CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(out_blob),
    )
    if not ok:
        raise OSError(ctypes.GetLastError(), "CryptProtectData failed")
    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        kernel32.LocalFree(ctypes.cast(out_blob.pbData, ctypes.c_void_p))


def _unprotect(data: bytes) -> bytes:
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    crypt32.CryptUnprotectData.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]

    in_blob, _buffer = _to_blob(data)
    out_blob = _DataBlob()
    ok = crypt32.CryptUnprotectData(
        ctypes.byref(in_blob),
        None,
        None,
        None,
        None,
        _CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(out_blob),
    )
    if not ok:
        raise OSError(ctypes.GetLastError(), "CryptUnprotectData failed")
    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        kernel32.LocalFree(ctypes.cast(out_blob.pbData, ctypes.c_void_p))


def is_encrypted(value: str) -> bool:
    return bool(value) and value.startswith(PREFIX)


def encrypt_secret(value: str) -> str:
    """Encrypt for the current Windows user; plain text is left untouched."""
    if not value or is_encrypted(value) or not sys.platform.startswith("win"):
        return value
    try:
        protected = _protect(value.encode("utf-8"))
    except Exception:
        # Never lose a key because DPAPI refused; the caller still has a
        # working (if weaker) configuration.
        return value
    return PREFIX + base64.b64encode(protected).decode("ascii")


def decrypt_secret(value: str) -> str:
    """Return the usable secret, accepting plain text from older configs."""
    if not value or not is_encrypted(value):
        return value
    try:
        raw = base64.b64decode(value[len(PREFIX) :])
        return _unprotect(raw).decode("utf-8")
    except Exception:
        return ""
