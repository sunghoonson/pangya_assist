# -*- coding: utf-8 -*-
"""
pangya_hw_watch_spin_curve_access.py

하드웨어 데이터 브레이크포인트로 실시간 스핀/커브 주소를 누가 읽고/쓰는지 추적합니다.
- 코드 패치/inlined hook 없음
- 대상 32-bit ProjectG127.exe를 Windows DebugActiveProcess로 attach
- WOW64 x86 debug registers DR0~DR3 사용

사용 예:
  python .\pangya_hw_watch_spin_curve_access.py --process ProjectG127.exe --base 0x165FB5F8
  python .\pangya_hw_watch_spin_curve_access.py --process ProjectG127.exe --curve 0x165FB5F8 --spin 0x165FB5FC
  python .\pangya_hw_watch_spin_curve_access.py --process ProjectG127.exe --base 0x165FB5F8 --watch-max

중요:
- x32dbg/CE debugger 등 다른 디버거가 붙어 있으면 실패할 수 있습니다.
- 관리자 권한 터미널 권장.
- 종료는 Ctrl+C.
"""

import argparse
import ctypes
import csv
import datetime as _dt
import os
import struct
import sys
import time
from ctypes import wintypes

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
psapi = ctypes.WinDLL("psapi", use_last_error=True)

# ---------- Win constants ----------
TH32CS_SNAPPROCESS = 0x00000002
TH32CS_SNAPTHREAD = 0x00000004
INVALID_HANDLE_VALUE = wintypes.HANDLE(-1).value

PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_VM_READ = 0x0010
PROCESS_ALL_ACCESS = 0x001F0FFF
THREAD_GET_CONTEXT = 0x0008
THREAD_SET_CONTEXT = 0x0010
THREAD_SUSPEND_RESUME = 0x0002
THREAD_QUERY_INFORMATION = 0x0040
THREAD_ALL_NEEDED = THREAD_GET_CONTEXT | THREAD_SET_CONTEXT | THREAD_SUSPEND_RESUME | THREAD_QUERY_INFORMATION

DBG_CONTINUE = 0x00010002
DBG_EXCEPTION_NOT_HANDLED = 0x80010001
INFINITE = 0xFFFFFFFF

EXCEPTION_DEBUG_EVENT = 1
CREATE_THREAD_DEBUG_EVENT = 2
CREATE_PROCESS_DEBUG_EVENT = 3
EXIT_THREAD_DEBUG_EVENT = 4
EXIT_PROCESS_DEBUG_EVENT = 5
LOAD_DLL_DEBUG_EVENT = 6
UNLOAD_DLL_DEBUG_EVENT = 7
OUTPUT_DEBUG_STRING_EVENT = 8
RIP_EVENT = 9

EXCEPTION_BREAKPOINT = 0x80000003
EXCEPTION_SINGLE_STEP = 0x80000004

WOW64_CONTEXT_i386 = 0x00010000
WOW64_CONTEXT_CONTROL = WOW64_CONTEXT_i386 | 0x00000001
WOW64_CONTEXT_INTEGER = WOW64_CONTEXT_i386 | 0x00000002
WOW64_CONTEXT_SEGMENTS = WOW64_CONTEXT_i386 | 0x00000004
WOW64_CONTEXT_DEBUG_REGISTERS = WOW64_CONTEXT_i386 | 0x00000010
WOW64_CONTEXT_FULL = WOW64_CONTEXT_CONTROL | WOW64_CONTEXT_INTEGER | WOW64_CONTEXT_SEGMENTS
WOW64_CONTEXT_FLAGS = WOW64_CONTEXT_FULL | WOW64_CONTEXT_DEBUG_REGISTERS

MAX_PATH = 260

# ---------- Structures ----------
class PROCESSENTRY32(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", wintypes.LONG),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", ctypes.c_char * MAX_PATH),
    ]

class THREADENTRY32(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ThreadID", wintypes.DWORD),
        ("th32OwnerProcessID", wintypes.DWORD),
        ("tpBasePri", wintypes.LONG),
        ("tpDeltaPri", wintypes.LONG),
        ("dwFlags", wintypes.DWORD),
    ]

class WOW64_FLOATING_SAVE_AREA(ctypes.Structure):
    _fields_ = [
        ("ControlWord", wintypes.DWORD),
        ("StatusWord", wintypes.DWORD),
        ("TagWord", wintypes.DWORD),
        ("ErrorOffset", wintypes.DWORD),
        ("ErrorSelector", wintypes.DWORD),
        ("DataOffset", wintypes.DWORD),
        ("DataSelector", wintypes.DWORD),
        ("RegisterArea", ctypes.c_ubyte * 80),
        ("Cr0NpxState", wintypes.DWORD),
    ]

class WOW64_CONTEXT(ctypes.Structure):
    _fields_ = [
        ("ContextFlags", wintypes.DWORD),
        ("Dr0", wintypes.DWORD),
        ("Dr1", wintypes.DWORD),
        ("Dr2", wintypes.DWORD),
        ("Dr3", wintypes.DWORD),
        ("Dr6", wintypes.DWORD),
        ("Dr7", wintypes.DWORD),
        ("FloatSave", WOW64_FLOATING_SAVE_AREA),
        ("SegGs", wintypes.DWORD),
        ("SegFs", wintypes.DWORD),
        ("SegEs", wintypes.DWORD),
        ("SegDs", wintypes.DWORD),
        ("Edi", wintypes.DWORD),
        ("Esi", wintypes.DWORD),
        ("Ebx", wintypes.DWORD),
        ("Edx", wintypes.DWORD),
        ("Ecx", wintypes.DWORD),
        ("Eax", wintypes.DWORD),
        ("Ebp", wintypes.DWORD),
        ("Eip", wintypes.DWORD),
        ("SegCs", wintypes.DWORD),
        ("EFlags", wintypes.DWORD),
        ("Esp", wintypes.DWORD),
        ("SegSs", wintypes.DWORD),
        ("ExtendedRegisters", ctypes.c_ubyte * 512),
    ]

class EXCEPTION_RECORD(ctypes.Structure):
    _fields_ = [
        ("ExceptionCode", wintypes.DWORD),
        ("ExceptionFlags", wintypes.DWORD),
        ("ExceptionRecord", ctypes.c_void_p),
        ("ExceptionAddress", ctypes.c_void_p),
        ("NumberParameters", wintypes.DWORD),
        ("ExceptionInformation", ctypes.c_size_t * 15),
    ]

class EXCEPTION_DEBUG_INFO(ctypes.Structure):
    _fields_ = [("ExceptionRecord", EXCEPTION_RECORD), ("dwFirstChance", wintypes.DWORD)]

class DEBUG_EVENT_UNION(ctypes.Union):
    _fields_ = [("Exception", EXCEPTION_DEBUG_INFO), ("raw", ctypes.c_ubyte * 160)]

class DEBUG_EVENT(ctypes.Structure):
    _fields_ = [
        ("dwDebugEventCode", wintypes.DWORD),
        ("dwProcessId", wintypes.DWORD),
        ("dwThreadId", wintypes.DWORD),
        ("u", DEBUG_EVENT_UNION),
    ]

class MODULEINFO(ctypes.Structure):
    _fields_ = [
        ("lpBaseOfDll", ctypes.c_void_p),
        ("SizeOfImage", wintypes.DWORD),
        ("EntryPoint", ctypes.c_void_p),
    ]

# ---------- API prototypes ----------
kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
kernel32.Process32First.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32)]
kernel32.Process32First.restype = wintypes.BOOL
kernel32.Process32Next.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32)]
kernel32.Process32Next.restype = wintypes.BOOL
kernel32.Thread32First.argtypes = [wintypes.HANDLE, ctypes.POINTER(THREADENTRY32)]
kernel32.Thread32First.restype = wintypes.BOOL
kernel32.Thread32Next.argtypes = [wintypes.HANDLE, ctypes.POINTER(THREADENTRY32)]
kernel32.Thread32Next.restype = wintypes.BOOL
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.CloseHandle.restype = wintypes.BOOL
kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.OpenThread.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.OpenThread.restype = wintypes.HANDLE
kernel32.ReadProcessMemory.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
kernel32.ReadProcessMemory.restype = wintypes.BOOL
kernel32.DebugActiveProcess.argtypes = [wintypes.DWORD]
kernel32.DebugActiveProcess.restype = wintypes.BOOL
kernel32.DebugActiveProcessStop.argtypes = [wintypes.DWORD]
kernel32.DebugActiveProcessStop.restype = wintypes.BOOL
kernel32.DebugSetProcessKillOnExit.argtypes = [wintypes.BOOL]
kernel32.DebugSetProcessKillOnExit.restype = wintypes.BOOL
kernel32.WaitForDebugEvent.argtypes = [ctypes.POINTER(DEBUG_EVENT), wintypes.DWORD]
kernel32.WaitForDebugEvent.restype = wintypes.BOOL
kernel32.ContinueDebugEvent.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.DWORD]
kernel32.ContinueDebugEvent.restype = wintypes.BOOL
kernel32.Wow64GetThreadContext.argtypes = [wintypes.HANDLE, ctypes.POINTER(WOW64_CONTEXT)]
kernel32.Wow64GetThreadContext.restype = wintypes.BOOL
kernel32.Wow64SetThreadContext.argtypes = [wintypes.HANDLE, ctypes.POINTER(WOW64_CONTEXT)]
kernel32.Wow64SetThreadContext.restype = wintypes.BOOL

psapi.EnumProcessModules.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.HMODULE), wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
psapi.EnumProcessModules.restype = wintypes.BOOL
psapi.GetModuleBaseNameA.argtypes = [wintypes.HANDLE, wintypes.HMODULE, ctypes.c_char_p, wintypes.DWORD]
psapi.GetModuleBaseNameA.restype = wintypes.DWORD
psapi.GetModuleInformation.argtypes = [wintypes.HANDLE, wintypes.HMODULE, ctypes.POINTER(MODULEINFO), wintypes.DWORD]
psapi.GetModuleInformation.restype = wintypes.BOOL


def last_error_msg(prefix="WinAPI"):
    err = ctypes.get_last_error()
    return f"{prefix} failed, GetLastError={err}"


def parse_int(s):
    if isinstance(s, int):
        return s
    return int(str(s), 0)


def find_pid_by_name(name):
    snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snap == INVALID_HANDLE_VALUE:
        raise RuntimeError(last_error_msg("CreateToolhelp32Snapshot(process)"))
    try:
        pe = PROCESSENTRY32()
        pe.dwSize = ctypes.sizeof(pe)
        if not kernel32.Process32First(snap, ctypes.byref(pe)):
            raise RuntimeError(last_error_msg("Process32First"))
        name_l = name.lower()
        while True:
            exe = pe.szExeFile.decode("mbcs", errors="ignore")
            if exe.lower() == name_l:
                return int(pe.th32ProcessID)
            if not kernel32.Process32Next(snap, ctypes.byref(pe)):
                break
    finally:
        kernel32.CloseHandle(snap)
    return None


def enum_threads(pid):
    tids = []
    snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, 0)
    if snap == INVALID_HANDLE_VALUE:
        raise RuntimeError(last_error_msg("CreateToolhelp32Snapshot(thread)"))
    try:
        te = THREADENTRY32()
        te.dwSize = ctypes.sizeof(te)
        if not kernel32.Thread32First(snap, ctypes.byref(te)):
            return tids
        while True:
            if int(te.th32OwnerProcessID) == pid:
                tids.append(int(te.th32ThreadID))
            if not kernel32.Thread32Next(snap, ctypes.byref(te)):
                break
    finally:
        kernel32.CloseHandle(snap)
    return tids


def open_thread(tid):
    return kernel32.OpenThread(THREAD_ALL_NEEDED, False, tid)


def get_context(tid):
    h = open_thread(tid)
    if not h:
        return None, None
    ctx = WOW64_CONTEXT()
    ctx.ContextFlags = WOW64_CONTEXT_FLAGS
    ok = kernel32.Wow64GetThreadContext(h, ctypes.byref(ctx))
    if not ok:
        kernel32.CloseHandle(h)
        return None, None
    return h, ctx


def set_context_and_close(h, ctx):
    ok = kernel32.Wow64SetThreadContext(h, ctypes.byref(ctx))
    kernel32.CloseHandle(h)
    return bool(ok)


def build_dr7(num_slots, rw=3, length=3):
    # rw=3: data read/write, length=3: 4 bytes
    dr7 = 0
    for i in range(num_slots):
        dr7 |= 1 << (i * 2)  # L0/L1/L2/L3 enable
        dr7 |= (rw & 0x3) << (16 + i * 4)
        dr7 |= (length & 0x3) << (18 + i * 4)
    return dr7


def apply_breakpoints_to_thread(tid, addrs):
    h, ctx = get_context(tid)
    if not h:
        return False
    vals = list(addrs) + [0, 0, 0, 0]
    ctx.Dr0, ctx.Dr1, ctx.Dr2, ctx.Dr3 = [int(v) & 0xFFFFFFFF for v in vals[:4]]
    ctx.Dr6 = 0
    ctx.Dr7 = build_dr7(len(addrs), rw=3, length=3)
    ok = set_context_and_close(h, ctx)
    return ok


def clear_breakpoints_from_thread(tid):
    h, ctx = get_context(tid)
    if not h:
        return False
    ctx.Dr0 = ctx.Dr1 = ctx.Dr2 = ctx.Dr3 = 0
    ctx.Dr6 = 0
    ctx.Dr7 = 0
    ok = set_context_and_close(h, ctx)
    return ok


def read_bytes(hproc, addr, size):
    buf = (ctypes.c_ubyte * size)()
    read = ctypes.c_size_t(0)
    if not kernel32.ReadProcessMemory(hproc, ctypes.c_void_p(addr), buf, size, ctypes.byref(read)):
        return None
    return bytes(buf[:read.value])


def read_f32(hproc, addr):
    b = read_bytes(hproc, addr, 4)
    if not b or len(b) < 4:
        return None
    return struct.unpack("<f", b)[0]


def get_modules(hproc):
    arr = (wintypes.HMODULE * 2048)()
    needed = wintypes.DWORD(0)
    modules = []
    if not psapi.EnumProcessModules(hproc, arr, ctypes.sizeof(arr), ctypes.byref(needed)):
        return modules
    count = min(int(needed.value // ctypes.sizeof(wintypes.HMODULE)), len(arr))
    for i in range(count):
        hmod = arr[i]
        name_buf = ctypes.create_string_buffer(MAX_PATH)
        psapi.GetModuleBaseNameA(hproc, hmod, name_buf, MAX_PATH)
        mi = MODULEINFO()
        if psapi.GetModuleInformation(hproc, hmod, ctypes.byref(mi), ctypes.sizeof(mi)):
            base = int(ctypes.cast(mi.lpBaseOfDll, ctypes.c_void_p).value or 0)
            size = int(mi.SizeOfImage)
            name = name_buf.value.decode("mbcs", errors="ignore")
            modules.append((base, base + size, name))
    modules.sort(key=lambda x: x[0])
    return modules


def module_label(mods, addr):
    for lo, hi, name in mods:
        if lo <= addr < hi:
            return f"{name}+0x{addr-lo:X}"
    return f"0x{addr:08X}"


def fmt_f(v):
    if v is None:
        return "NA"
    return f"{v:+.6f}"


def infer_reg_offsets(ctx, target_addr, max_abs=0x800):
    regs = {
        "eax": ctx.Eax,
        "ebx": ctx.Ebx,
        "ecx": ctx.Ecx,
        "edx": ctx.Edx,
        "esi": ctx.Esi,
        "edi": ctx.Edi,
        "ebp": ctx.Ebp,
        "esp": ctx.Esp,
    }
    hits = []
    for r, val in regs.items():
        off = (target_addr - int(val)) & 0xFFFFFFFF
        # signed 32
        if off & 0x80000000:
            off -= 0x100000000
        if -max_abs <= off <= max_abs:
            if off >= 0:
                hits.append(f"{r}+0x{off:X}")
            else:
                hits.append(f"{r}-0x{-off:X}")
    return ",".join(hits)


def ensure_dir(path):
    os.makedirs(path, exist_ok=True)


def main():
    ap = argparse.ArgumentParser(description="Pangya spin/curve hardware access tracer")
    ap.add_argument("--process", default="ProjectG127.exe", help="process name")
    ap.add_argument("--pid", type=int, default=None)
    ap.add_argument("--base", type=parse_int, default=None, help="curve field address; spin is base+4")
    ap.add_argument("--curve", type=parse_int, default=None, help="curve address")
    ap.add_argument("--spin", type=parse_int, default=None, help="spin address")
    ap.add_argument("--watch-max", action="store_true", help="also watch curve_max/spin_max at +8/+C")
    ap.add_argument("--max-events", type=int, default=0, help="0 = unlimited")
    ap.add_argument("--print-every", type=int, default=1, help="print every Nth event per eip/slot")
    ap.add_argument("--out-dir", default=os.path.join("logs", "hw_watch_spin_curve_access"))
    args = ap.parse_args()

    pid = args.pid or find_pid_by_name(args.process)
    if not pid:
        print(f"[ERROR] process not found: {args.process}")
        return 2

    if args.curve is None:
        if args.base is None:
            print("[ERROR] --base 또는 --curve/--spin 을 지정하세요")
            return 2
        curve_addr = args.base
    else:
        curve_addr = args.curve
    spin_addr = args.spin if args.spin is not None else curve_addr + 4

    targets = [("curve", curve_addr), ("spin", spin_addr)]
    if args.watch_max:
        targets += [("curve_max", curve_addr + 8), ("spin_max", curve_addr + 12)]
    if len(targets) > 4:
        print("[ERROR] hardware breakpoint slot은 최대 4개입니다")
        return 2

    hproc = kernel32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid)
    if not hproc:
        print(f"[ERROR] OpenProcess 실패: {ctypes.get_last_error()}")
        return 1

    mods = get_modules(hproc)
    now = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    ensure_dir(args.out_dir)
    csv_path = os.path.join(args.out_dir, f"hw_watch_spin_curve_access_{now}.csv")
    txt_path = os.path.join(args.out_dir, f"hw_watch_spin_curve_access_{now}.txt")

    print(f"[INFO] attached target pid={pid}, process={args.process}")
    print("[INFO] hardware data breakpoint, read/write access")
    for i, (name, addr) in enumerate(targets):
        val = read_f32(hproc, addr)
        print(f"[TARGET] DR{i} {name:9s} 0x{addr:08X} = {fmt_f(val)}")
    print(f"[INFO] csv={csv_path}")
    print(f"[INFO] txt={txt_path}")
    print("[INFO] DebugActiveProcess attach 중... 다른 디버거가 붙어 있으면 실패합니다.")

    if not kernel32.DebugActiveProcess(pid):
        print(f"[ERROR] DebugActiveProcess 실패 GetLastError={ctypes.get_last_error()}  관리자 권한/다른 디버거 여부 확인")
        kernel32.CloseHandle(hproc)
        return 1
    kernel32.DebugSetProcessKillOnExit(False)

    attached = True
    event_count = 0
    per_site_count = {}
    seen_threads = set()

    def apply_all_threads():
        tids = enum_threads(pid)
        ok_count = 0
        for tid in tids:
            if apply_breakpoints_to_thread(tid, [a for _, a in targets]):
                ok_count += 1
                seen_threads.add(tid)
        print(f"[BP] applied to {ok_count}/{len(tids)} threads")

    def clear_all_threads():
        tids = enum_threads(pid)
        for tid in tids:
            clear_breakpoints_from_thread(tid)

    with open(csv_path, "w", newline="", encoding="utf-8-sig") as fcsv, open(txt_path, "w", encoding="utf-8") as ftxt:
        writer = csv.DictWriter(fcsv, fieldnames=[
            "seq", "time", "tid", "slot", "target_name", "target_addr",
            "eip", "eip_label", "dr6", "instr_bytes",
            "curve", "spin", "curve_max", "spin_max",
            "eax", "ebx", "ecx", "edx", "esi", "edi", "ebp", "esp",
            "reg_offset_hint",
        ])
        writer.writeheader()

        ftxt.write(f"pid={pid}\n")
        for i, (name, addr) in enumerate(targets):
            ftxt.write(f"DR{i} {name} 0x{addr:08X}\n")
        ftxt.write("\n")
        ftxt.flush()

        try:
            apply_all_threads()
            print("[INFO] 실행 중입니다. 게임에서 스핀/커브를 움직이거나 샷을 눌러보세요. 종료: Ctrl+C")
            while True:
                dbg = DEBUG_EVENT()
                ok = kernel32.WaitForDebugEvent(ctypes.byref(dbg), 1000)
                if not ok:
                    # 새 스레드가 생겼는데 create event를 놓치는 경우 대비해 가끔 재적용
                    current = set(enum_threads(pid))
                    new = current - seen_threads
                    for tid in new:
                        if apply_breakpoints_to_thread(tid, [a for _, a in targets]):
                            seen_threads.add(tid)
                            print(f"[BP] applied new thread tid={tid}")
                    continue

                code = int(dbg.dwDebugEventCode)
                tid = int(dbg.dwThreadId)
                continue_status = DBG_CONTINUE

                if code == CREATE_THREAD_DEBUG_EVENT:
                    if apply_breakpoints_to_thread(tid, [a for _, a in targets]):
                        seen_threads.add(tid)
                        print(f"[BP] CREATE_THREAD tid={tid}")

                elif code == CREATE_PROCESS_DEBUG_EVENT:
                    # attach 초기 이벤트 후 재적용
                    apply_all_threads()

                elif code == EXIT_PROCESS_DEBUG_EVENT:
                    print("[INFO] target process exited")
                    break

                elif code == EXCEPTION_DEBUG_EVENT:
                    ex = dbg.u.Exception.ExceptionRecord
                    ex_code = int(ex.ExceptionCode)
                    if ex_code == EXCEPTION_SINGLE_STEP:
                        hthr, ctx = get_context(tid)
                        if hthr:
                            # DR6를 읽은 뒤 clear. DR7은 유지.
                            dr6 = int(ctx.Dr6)
                            eip = int(ctx.Eip)
                            hit_slots = [i for i in range(len(targets)) if dr6 & (1 << i)]
                            if not hit_slots:
                                hit_slots = [-1]
                            # 다음 exception 오염 방지
                            ctx.Dr6 = 0
                            # resume flag; 일부 CPU/상황에서 같은 명령 재트랩 완화
                            ctx.EFlags |= 0x10000
                            set_context_and_close(hthr, ctx)

                            for slot in hit_slots:
                                if slot < 0 or slot >= len(targets):
                                    tname, taddr = ("unknown", 0)
                                else:
                                    tname, taddr = targets[slot]
                                event_count += 1
                                key = (eip, slot)
                                per_site_count[key] = per_site_count.get(key, 0) + 1
                                instr = read_bytes(hproc, eip, 16) or b""
                                curve = read_f32(hproc, curve_addr)
                                spin = read_f32(hproc, spin_addr)
                                cmax = read_f32(hproc, curve_addr + 8)
                                smax = read_f32(hproc, curve_addr + 12)
                                hint = infer_reg_offsets(ctx, taddr, max_abs=0x1000) if taddr else ""
                                row = {
                                    "seq": event_count,
                                    "time": time.time(),
                                    "tid": tid,
                                    "slot": slot,
                                    "target_name": tname,
                                    "target_addr": f"0x{taddr:08X}" if taddr else "",
                                    "eip": f"0x{eip:08X}",
                                    "eip_label": module_label(mods, eip),
                                    "dr6": f"0x{dr6:08X}",
                                    "instr_bytes": instr.hex(" ").upper(),
                                    "curve": curve,
                                    "spin": spin,
                                    "curve_max": cmax,
                                    "spin_max": smax,
                                    "eax": f"0x{int(ctx.Eax):08X}",
                                    "ebx": f"0x{int(ctx.Ebx):08X}",
                                    "ecx": f"0x{int(ctx.Ecx):08X}",
                                    "edx": f"0x{int(ctx.Edx):08X}",
                                    "esi": f"0x{int(ctx.Esi):08X}",
                                    "edi": f"0x{int(ctx.Edi):08X}",
                                    "ebp": f"0x{int(ctx.Ebp):08X}",
                                    "esp": f"0x{int(ctx.Esp):08X}",
                                    "reg_offset_hint": hint,
                                }
                                writer.writerow(row)
                                fcsv.flush()

                                should_print = per_site_count[key] == 1 or (args.print_every > 0 and per_site_count[key] % args.print_every == 0)
                                if should_print:
                                    msg = (
                                        f"[HIT {event_count:05d}] tid={tid} {tname}@0x{taddr:08X} "
                                        f"EIP=0x{eip:08X}({module_label(mods, eip)}) "
                                        f"count={per_site_count[key]} C={fmt_f(curve)} S={fmt_f(spin)} "
                                        f"hint={hint} bytes={instr[:8].hex(' ').upper()}"
                                    )
                                    print(msg)
                                    ftxt.write(msg + "\n")
                                    ftxt.flush()

                                if args.max_events and event_count >= args.max_events:
                                    raise KeyboardInterrupt
                    elif ex_code == EXCEPTION_BREAKPOINT:
                        # attach 초기 breakpoint는 정상
                        continue_status = DBG_CONTINUE
                    else:
                        # 다른 예외는 대상 프로세스의 기존 핸들러가 처리하게 넘김
                        continue_status = DBG_EXCEPTION_NOT_HANDLED

                kernel32.ContinueDebugEvent(dbg.dwProcessId, dbg.dwThreadId, continue_status)

        except KeyboardInterrupt:
            print("\n[INFO] 종료 요청")
        finally:
            try:
                clear_all_threads()
                print("[BP] cleared")
            except Exception as e:
                print(f"[WARN] clear bp 실패: {e}")
            if attached:
                kernel32.DebugActiveProcessStop(pid)
                print("[INFO] DebugActiveProcessStop")
            kernel32.CloseHandle(hproc)

    print(f"[DONE] events={event_count}")
    print(f"[DONE] csv={csv_path}")
    print(f"[DONE] txt={txt_path}")
    return 0


if __name__ == "__main__":
    if os.name != "nt":
        print("Windows 전용 스크립트입니다.")
        sys.exit(1)
    sys.exit(main())
