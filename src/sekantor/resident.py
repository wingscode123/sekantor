"""Keep the hub in RAM on Windows (ADR-0020).

Under memory pressure Windows moved two thirds of an idle hub to the page file, and every event then
waited 1-6 s for the hub's memory to come back, past the hook's 1 s timeout. A hard minimum working
set stops Windows from trimming the hub below it. Elsewhere this does nothing.
"""

from __future__ import annotations

import sys

MIN_BYTES = 96 * 2**20  # a fresh hub uses about 75 MB of RAM
MAX_BYTES = 1024 * 2**20  # ignored: the maximum is left soft

QUOTA_LIMITS_HARDWS_MIN_ENABLE = 0x1
QUOTA_LIMITS_HARDWS_MAX_DISABLE = 0x8
TOKEN_ADJUST_PRIVILEGES, TOKEN_QUERY = 0x20, 0x8
SE_PRIVILEGE_ENABLED = 0x2
ERROR_NOT_ALL_ASSIGNED = 1300


def keep_resident(min_bytes: int = MIN_BYTES) -> str | None:
    """None when done, else why not. Never raises: the hub runs either way."""
    if sys.platform != "win32":
        return "only on Windows"
    try:
        return _windows(min_bytes)
    except Exception as e:  # noqa: BLE001 - an unusual Windows must not stop the hub
        return f"{type(e).__name__}: {e}"


def _windows(min_bytes: int) -> str | None:
    import ctypes
    from ctypes import wintypes as w

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    adv = ctypes.WinDLL("advapi32", use_last_error=True)
    k32.GetCurrentProcess.restype = w.HANDLE
    k32.CloseHandle.argtypes = [w.HANDLE]
    adv.OpenProcessToken.argtypes = [w.HANDLE, w.DWORD, ctypes.POINTER(w.HANDLE)]
    adv.LookupPrivilegeValueW.argtypes = [w.LPCWSTR, w.LPCWSTR, ctypes.c_void_p]

    class LUID(ctypes.Structure):
        _fields_ = [("LowPart", w.DWORD), ("HighPart", w.LONG)]

    class TOKEN_PRIVILEGES(ctypes.Structure):
        _fields_ = [("PrivilegeCount", w.DWORD), ("Luid", LUID), ("Attributes", w.DWORD)]

    adv.AdjustTokenPrivileges.argtypes = [w.HANDLE, w.BOOL, ctypes.POINTER(TOKEN_PRIVILEGES), w.DWORD,
                                          ctypes.c_void_p, ctypes.c_void_p]
    k32.SetProcessWorkingSetSizeEx.argtypes = [w.HANDLE, ctypes.c_size_t, ctypes.c_size_t, w.DWORD]

    # A hard minimum needs SeIncreaseWorkingSetPrivilege enabled. Users hold it, disabled.
    process = k32.GetCurrentProcess()
    token = w.HANDLE()
    if not adv.OpenProcessToken(process, TOKEN_ADJUST_PRIVILEGES | TOKEN_QUERY, ctypes.byref(token)):
        return f"OpenProcessToken failed ({ctypes.get_last_error()})"
    try:
        tp = TOKEN_PRIVILEGES(1, LUID(), SE_PRIVILEGE_ENABLED)
        if not adv.LookupPrivilegeValueW(None, "SeIncreaseWorkingSetPrivilege", ctypes.byref(tp.Luid)):
            return f"LookupPrivilegeValue failed ({ctypes.get_last_error()})"
        ok = adv.AdjustTokenPrivileges(token, False, ctypes.byref(tp), 0, None, None)
        if not ok or ctypes.get_last_error() == ERROR_NOT_ALL_ASSIGNED:
            return "this account may not raise its working set (SeIncreaseWorkingSetPrivilege)"
    finally:
        k32.CloseHandle(token)
    flags = QUOTA_LIMITS_HARDWS_MIN_ENABLE | QUOTA_LIMITS_HARDWS_MAX_DISABLE
    if not k32.SetProcessWorkingSetSizeEx(process, min_bytes, max(MAX_BYTES, min_bytes), flags):
        return f"SetProcessWorkingSetSizeEx failed ({ctypes.get_last_error()})"
    return None
