# -*- coding: utf-8 -*-
"""
pangya_spin_curve_live_rescan_probe.py

Read-only live spin/curve probe for Pangya ProjectG127.exe.

이 버전의 목적
- heap 주소가 클라 재실행/방 이동 때 바뀌는 문제를 해결하기 위해,
  고정 주소/holder를 믿지 않는다.
- 최초 1회 signature scan으로 구조체를 찾고, 이후에는 base+offset만 읽는다.
- 방 이동 등으로 base가 깨지면 그때만 다시 scan한다.
- 따라서 매 tick 전체 스캔하는 방식보다 가볍고, 고정 heap 주소 방식보다 안정적이다.

확인된 구조:
  struct_base + 0x18 = current curve float
  struct_base + 0x1C = current spin float
  struct_base + 0x20 = max curve float  (기본 23.0)
  struct_base + 0x24 = max spin float   (기본 30.0)

사용 예:
  python .\pangya_spin_curve_live_rescan_probe.py --process ProjectG127.exe
  python .\pangya_spin_curve_live_rescan_probe.py --process ProjectG127.exe --select-seconds 8
  python .\pangya_spin_curve_live_rescan_probe.py --process ProjectG127.exe --curve-max 23 --spin-max 30

권장 테스트:
  1) 게임룸 샷대기 진입
  2) 실행 후 select 시간 동안 스핀/커브를 조금 움직임
  3) 방 나가기/재입장
  4) 자동으로 invalid 감지 후 새 base를 다시 잡는지 확인

출력:
  pangya_spin_curve_live.json
  logs\spin_curve_live_rescan\spin_curve_live_rescan_YYYYMMDD_HHMMSS.csv

주의:
- 코드 후킹/디버거 attach 없음. ReadProcessMemory만 사용.
- 후보가 여러 개일 때는 움직임 점수가 가장 큰 후보를 선택한다.
"""

from __future__ import annotations

import argparse
import csv
import ctypes
import ctypes.wintypes as wt
import json
import math
import os
import struct
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_VM_READ = 0x0010
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
PROCESS_NEEDED = PROCESS_QUERY_INFORMATION | PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_VM_READ

TH32CS_SNAPPROCESS = 0x00000002
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

MEM_COMMIT = 0x1000
MEM_PRIVATE = 0x20000
MEM_MAPPED = 0x40000
MEM_IMAGE = 0x1000000

PAGE_NOACCESS = 0x01
PAGE_READONLY = 0x02
PAGE_READWRITE = 0x04
PAGE_WRITECOPY = 0x08
PAGE_EXECUTE = 0x10
PAGE_EXECUTE_READ = 0x20
PAGE_EXECUTE_READWRITE = 0x40
PAGE_EXECUTE_WRITECOPY = 0x80
PAGE_GUARD = 0x100

READABLE_PROTECTS = {
    PAGE_READONLY,
    PAGE_READWRITE,
    PAGE_WRITECOPY,
    PAGE_EXECUTE_READ,
    PAGE_EXECUTE_READWRITE,
    PAGE_EXECUTE_WRITECOPY,
}
WRITABLE_PROTECTS = {
    PAGE_READWRITE,
    PAGE_WRITECOPY,
    PAGE_EXECUTE_READWRITE,
    PAGE_EXECUTE_WRITECOPY,
}


class PROCESSENTRY32(ctypes.Structure):
    _fields_ = [
        ("dwSize", wt.DWORD),
        ("cntUsage", wt.DWORD),
        ("th32ProcessID", wt.DWORD),
        ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", wt.DWORD),
        ("cntThreads", wt.DWORD),
        ("th32ParentProcessID", wt.DWORD),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", wt.DWORD),
        ("szExeFile", ctypes.c_char * 260),
    ]


class MEMORY_BASIC_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BaseAddress", ctypes.c_void_p),
        ("AllocationBase", ctypes.c_void_p),
        ("AllocationProtect", wt.DWORD),
        ("RegionSize", ctypes.c_size_t),
        ("State", wt.DWORD),
        ("Protect", wt.DWORD),
        ("Type", wt.DWORD),
    ]


kernel32.CreateToolhelp32Snapshot.argtypes = [wt.DWORD, wt.DWORD]
kernel32.CreateToolhelp32Snapshot.restype = wt.HANDLE
kernel32.Process32First.argtypes = [wt.HANDLE, ctypes.POINTER(PROCESSENTRY32)]
kernel32.Process32First.restype = wt.BOOL
kernel32.Process32Next.argtypes = [wt.HANDLE, ctypes.POINTER(PROCESSENTRY32)]
kernel32.Process32Next.restype = wt.BOOL
kernel32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
kernel32.OpenProcess.restype = wt.HANDLE
kernel32.CloseHandle.argtypes = [wt.HANDLE]
kernel32.CloseHandle.restype = wt.BOOL
kernel32.ReadProcessMemory.argtypes = [wt.HANDLE, wt.LPCVOID, wt.LPVOID, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
kernel32.ReadProcessMemory.restype = wt.BOOL
kernel32.VirtualQueryEx.argtypes = [wt.HANDLE, wt.LPCVOID, ctypes.POINTER(MEMORY_BASIC_INFORMATION), ctypes.c_size_t]
kernel32.VirtualQueryEx.restype = ctypes.c_size_t


def parse_int(s: str) -> int:
    return int(str(s).strip(), 0)


def find_pid_by_name(name: str) -> int:
    snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snap == INVALID_HANDLE_VALUE:
        raise OSError(ctypes.get_last_error(), "CreateToolhelp32Snapshot failed")
    try:
        pe = PROCESSENTRY32()
        pe.dwSize = ctypes.sizeof(PROCESSENTRY32)
        if not kernel32.Process32First(snap, ctypes.byref(pe)):
            raise OSError(ctypes.get_last_error(), "Process32First failed")
        wanted = name.lower()
        while True:
            exe = pe.szExeFile.split(b"\x00", 1)[0].decode("mbcs", errors="replace")
            if exe.lower() == wanted:
                return int(pe.th32ProcessID)
            if not kernel32.Process32Next(snap, ctypes.byref(pe)):
                break
    finally:
        kernel32.CloseHandle(snap)
    raise RuntimeError(f"process not found: {name}")


def open_process(pid: int) -> int:
    h = kernel32.OpenProcess(PROCESS_NEEDED, False, pid)
    if not h:
        raise OSError(ctypes.get_last_error(), f"OpenProcess failed pid={pid}. 관리자 권한을 확인하세요")
    return int(h)


def is_readable(protect: int) -> bool:
    if protect & (PAGE_GUARD | PAGE_NOACCESS):
        return False
    return (protect & 0xFF) in READABLE_PROTECTS


def is_writable(protect: int) -> bool:
    if protect & (PAGE_GUARD | PAGE_NOACCESS):
        return False
    return (protect & 0xFF) in WRITABLE_PROTECTS


def type_name(t: int) -> str:
    if t == MEM_PRIVATE:
        return "PRIVATE"
    if t == MEM_MAPPED:
        return "MAPPED"
    if t == MEM_IMAGE:
        return "IMAGE"
    return f"0x{t:X}"


def rpm(hproc: int, addr: int, size: int) -> bytes:
    buf = (ctypes.c_ubyte * size)()
    read = ctypes.c_size_t(0)
    ok = kernel32.ReadProcessMemory(hproc, ctypes.c_void_p(addr), buf, size, ctypes.byref(read))
    if not ok or read.value != size:
        return b""
    return bytes(buf)


def read_f32(hproc: int, addr: int) -> Optional[float]:
    b = rpm(hproc, addr, 4)
    if len(b) != 4:
        return None
    v = struct.unpack("<f", b)[0]
    if not math.isfinite(v):
        return None
    return v


def collect_regions(hproc: int, *, mode: str, max_region_mb: float, va_min: int, va_max: int) -> List[Dict[str, int]]:
    regions: List[Dict[str, int]] = []
    mbi = MEMORY_BASIC_INFORMATION()
    mbi_size = ctypes.sizeof(mbi)
    addr = va_min
    max_region = int(max_region_mb * 1024 * 1024)

    while addr < va_max:
        r = kernel32.VirtualQueryEx(hproc, ctypes.c_void_p(addr), ctypes.byref(mbi), mbi_size)
        if not r:
            addr += 0x10000
            continue
        base = int(mbi.BaseAddress or 0)
        size = int(mbi.RegionSize or 0)
        end = base + size
        if size <= 0:
            addr += 0x1000
            continue

        ok = mbi.State == MEM_COMMIT and is_readable(int(mbi.Protect))
        if mode == "private_rw":
            ok = ok and int(mbi.Type) == MEM_PRIVATE and is_writable(int(mbi.Protect))
        elif mode == "rw":
            ok = ok and is_writable(int(mbi.Protect)) and int(mbi.Type) in (MEM_PRIVATE, MEM_MAPPED)
        elif mode == "all":
            ok = ok and int(mbi.Type) in (MEM_PRIVATE, MEM_MAPPED, MEM_IMAGE)
        else:
            raise ValueError(f"unknown mode: {mode}")

        if size > max_region:
            ok = False
        if end < 0x10000:
            ok = False
        if ok:
            regions.append({
                "base": base,
                "end": end,
                "size": size,
                "protect": int(mbi.Protect),
                "type": int(mbi.Type),
            })
        addr = max(end, addr + 0x1000)
    return regions


def nearly(v: float, target: float, eps: float) -> bool:
    return math.isfinite(v) and abs(v - target) <= eps


def valid_candidate_values(curve: float, spin: float, cmax: float, smax: float, curve_max: float, spin_max: float, eps: float) -> bool:
    if not all(math.isfinite(x) for x in (curve, spin, cmax, smax)):
        return False
    if not nearly(cmax, curve_max, eps):
        return False
    if not nearly(smax, spin_max, eps):
        return False
    # 현재값은 최대값보다 약간 넘을 수 있어서 여유를 둔다.
    if abs(curve) > abs(curve_max) + 2.0:
        return False
    if abs(spin) > abs(spin_max) + 2.0:
        return False
    return True


def read_struct_values(hproc: int, struct_base: int, offsets: Tuple[int, int, int, int]) -> Optional[Tuple[float, float, float, float]]:
    co, so, cmo, smo = offsets
    vals = []
    for off in (co, so, cmo, smo):
        v = read_f32(hproc, struct_base + off)
        if v is None:
            return None
        vals.append(v)
    return vals[0], vals[1], vals[2], vals[3]


def scan_candidates(hproc: int, regions: List[Dict[str, int]], *, curve_max: float, spin_max: float,
                    offsets: Tuple[int, int, int, int], eps: float, limit: int) -> List[Dict[str, object]]:
    co, so, cmo, smo = offsets
    if smo != cmo + 4:
        raise ValueError("현재 scanner는 curve_max/spin_max가 연속된 float일 때만 지원합니다")
    pair = struct.pack("<ff", float(curve_max), float(spin_max))
    candidates: List[Dict[str, object]] = []
    seen = set()

    for reg in regions:
        base = int(reg["base"])
        size = int(reg["size"])
        data = rpm(hproc, base, size)
        if len(data) < 8:
            continue
        start = 0
        while True:
            idx = data.find(pair, start)
            if idx < 0:
                break
            pair_addr = base + idx
            # float alignment 선호. 완전 차단하지 않고 4바이트 정렬만 사용.
            if (pair_addr & 3) == 0:
                struct_base = pair_addr - cmo
                if struct_base >= base and struct_base + max(offsets) + 4 <= base + len(data):
                    rel = struct_base - base
                    try:
                        curve = struct.unpack_from("<f", data, rel + co)[0]
                        spin = struct.unpack_from("<f", data, rel + so)[0]
                        cmax = struct.unpack_from("<f", data, rel + cmo)[0]
                        smax = struct.unpack_from("<f", data, rel + smo)[0]
                    except Exception:
                        start = idx + 4
                        continue
                    if valid_candidate_values(curve, spin, cmax, smax, curve_max, spin_max, eps):
                        if struct_base not in seen:
                            seen.add(struct_base)
                            candidates.append({
                                "base": struct_base,
                                "curve": float(curve),
                                "spin": float(spin),
                                "curve_max": float(cmax),
                                "spin_max": float(smax),
                                "region_base": base,
                                "region_type": type_name(int(reg["type"])),
                                "score": 0.0,
                            })
                            if len(candidates) >= limit:
                                return candidates
            start = idx + 4
    return candidates


def choose_by_motion(hproc: int, candidates: List[Dict[str, object]], *, seconds: float, interval: float,
                     offsets: Tuple[int, int, int, int], curve_max: float, spin_max: float, eps: float) -> Dict[str, object]:
    if not candidates:
        raise RuntimeError("candidate가 없습니다")
    if len(candidates) == 1 or seconds <= 0:
        return candidates[0]

    states: Dict[int, Dict[str, object]] = {}
    for c in candidates:
        base = int(c["base"])
        vals = read_struct_values(hproc, base, offsets)
        if vals is None:
            continue
        states[base] = {"last": vals, "motion": 0.0, "valid_count": 0}

    end = time.time() + seconds
    while time.time() < end:
        for c in candidates:
            base = int(c["base"])
            st = states.get(base)
            if st is None:
                continue
            vals = read_struct_values(hproc, base, offsets)
            if vals is None:
                continue
            curve, spin, cmax, smax = vals
            if not valid_candidate_values(curve, spin, cmax, smax, curve_max, spin_max, eps):
                continue
            last = st["last"]
            st["motion"] = float(st["motion"]) + abs(curve - last[0]) + abs(spin - last[1])
            st["last"] = vals
            st["valid_count"] = int(st["valid_count"]) + 1
        time.sleep(max(0.01, interval))

    best = None
    best_score = -1.0
    for c in candidates:
        base = int(c["base"])
        st = states.get(base)
        if st is None:
            continue
        score = float(st["motion"]) + min(int(st["valid_count"]), 50) * 0.01
        c["score"] = score
        if score > best_score:
            best = c
            best_score = score
    return best or candidates[0]


def fmt_f(v: float) -> str:
    if abs(v) > 1e6:
        return f"{v:.3e}"
    return f"{v:+.6f}"


def write_json(path: Path, payload: Dict[str, object]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--process", default="ProjectG127.exe")
    ap.add_argument("--pid", type=int, default=None)
    ap.add_argument("--curve-max", type=float, default=23.0)
    ap.add_argument("--spin-max", type=float, default=30.0)
    ap.add_argument("--eps", type=float, default=0.001)
    ap.add_argument("--curve-offset", type=parse_int, default=0x18)
    ap.add_argument("--spin-offset", type=parse_int, default=0x1C)
    ap.add_argument("--curve-max-offset", type=parse_int, default=0x20)
    ap.add_argument("--spin-max-offset", type=parse_int, default=0x24)
    ap.add_argument("--interval", type=float, default=0.05)
    ap.add_argument("--select-seconds", type=float, default=5.0)
    ap.add_argument("--rescan-cooldown", type=float, default=1.0)
    ap.add_argument("--invalid-threshold", type=int, default=5)
    ap.add_argument("--mode", choices=["private_rw", "rw", "all"], default="private_rw")
    ap.add_argument("--max-region-mb", type=float, default=16.0)
    ap.add_argument("--va-min", type=parse_int, default=0x00010000)
    ap.add_argument("--va-max", type=parse_int, default=0x7FFFFFFF)
    ap.add_argument("--candidate-limit", type=int, default=64)
    ap.add_argument("--json", default="pangya_spin_curve_live.json")
    ap.add_argument("--print-only-changed", action="store_true")
    args = ap.parse_args()

    pid = args.pid if args.pid is not None else find_pid_by_name(args.process)
    hproc = open_process(pid)
    offsets = (args.curve_offset, args.spin_offset, args.curve_max_offset, args.spin_max_offset)

    log_dir = Path("logs") / "spin_curve_live_rescan"
    log_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = log_dir / f"spin_curve_live_rescan_{ts}.csv"
    json_path = Path(args.json)

    print(f"[INFO] attached pid={pid}, process={args.process}")
    print(f"[INFO] read-only rescan probe")
    print(f"[INFO] struct offsets curve=+0x{args.curve_offset:X}, spin=+0x{args.spin_offset:X}, curve_max=+0x{args.curve_max_offset:X}, spin_max=+0x{args.spin_max_offset:X}")
    print(f"[INFO] signature: [base+0x{args.curve_max_offset:X}]={args.curve_max}, [base+0x{args.spin_max_offset:X}]={args.spin_max}")
    print(f"[INFO] mode={args.mode}, select_seconds={args.select_seconds}, invalid_threshold={args.invalid_threshold}")
    print(f"[INFO] csv={csv_path}")
    print(f"[INFO] json={json_path.resolve()}")
    print("[INFO] 종료: Ctrl+C")

    regions = collect_regions(hproc, mode=args.mode, max_region_mb=args.max_region_mb, va_min=args.va_min, va_max=args.va_max)
    print(f"[INFO] scan_regions={len(regions)}")

    current_base: Optional[int] = None
    invalid_count = 0
    last_rescan = 0.0
    rescan_count = 0
    seq = 0
    last_print_tuple = None

    fieldnames = [
        "seq", "time", "ok", "reason", "base", "curve_addr", "spin_addr", "curve", "spin", "curve_max", "spin_max",
        "candidate_count", "selected_score", "rescan_count"
    ]

    def do_rescan(reason: str) -> Tuple[Optional[int], int, float]:
        nonlocal rescan_count, last_rescan
        rescan_count += 1
        last_rescan = time.time()
        cands = scan_candidates(
            hproc, regions,
            curve_max=args.curve_max,
            spin_max=args.spin_max,
            offsets=offsets,
            eps=args.eps,
            limit=args.candidate_limit,
        )
        print(f"[SCAN] reason={reason}, candidates={len(cands)}")
        if not cands:
            return None, 0, 0.0
        if len(cands) > 1 and args.select_seconds > 0:
            print(f"[SELECT] 후보 {len(cands)}개. {args.select_seconds:.1f}초 동안 스핀/커브를 움직이면 motion_score로 선택합니다.")
        selected = choose_by_motion(
            hproc, cands,
            seconds=args.select_seconds if len(cands) > 1 else 0.0,
            interval=args.interval,
            offsets=offsets,
            curve_max=args.curve_max,
            spin_max=args.spin_max,
            eps=args.eps,
        )
        base = int(selected["base"])
        score = float(selected.get("score", 0.0))
        vals = read_struct_values(hproc, base, offsets)
        print(f"[SELECT] base=0x{base:08X}, motion_score={score:.6f}, values={vals}")
        return base, len(cands), score

    try:
        current_base, cand_count, selected_score = do_rescan("startup")
        with csv_path.open("w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames)
            w.writeheader()
            while True:
                seq += 1
                now = time.time()
                row: Dict[str, object] = {
                    "seq": seq,
                    "time": now,
                    "ok": False,
                    "reason": "",
                    "base": "",
                    "curve_addr": "",
                    "spin_addr": "",
                    "curve": "",
                    "spin": "",
                    "curve_max": "",
                    "spin_max": "",
                    "candidate_count": cand_count if 'cand_count' in locals() else "",
                    "selected_score": selected_score if 'selected_score' in locals() else "",
                    "rescan_count": rescan_count,
                }

                if current_base is None:
                    row["reason"] = "no_base"
                    payload = {
                        "ok": False,
                        "reason": "no_base",
                        "source": "spin_curve_live_rescan",
                        "time": now,
                        "rescan_count": rescan_count,
                    }
                    write_json(json_path, payload)
                    if time.time() - last_rescan >= args.rescan_cooldown:
                        current_base, cand_count, selected_score = do_rescan("no_base")
                    w.writerow(row)
                    f.flush()
                    time.sleep(args.interval)
                    continue

                vals = read_struct_values(hproc, current_base, offsets)
                valid = False
                reason = ""
                if vals is None:
                    reason = "read_failed"
                else:
                    curve, spin, cmax, smax = vals
                    valid = valid_candidate_values(curve, spin, cmax, smax, args.curve_max, args.spin_max, args.eps)
                    if not valid:
                        reason = "invalid_values"

                if valid and vals is not None:
                    invalid_count = 0
                    curve, spin, cmax, smax = vals
                    row.update({
                        "ok": True,
                        "reason": "ok",
                        "base": f"0x{current_base:08X}",
                        "curve_addr": f"0x{current_base + args.curve_offset:08X}",
                        "spin_addr": f"0x{current_base + args.spin_offset:08X}",
                        "curve": curve,
                        "spin": spin,
                        "curve_max": cmax,
                        "spin_max": smax,
                        "rescan_count": rescan_count,
                    })
                    payload = {
                        "ok": True,
                        "source": "spin_curve_live_rescan_struct_signature",
                        "time": now,
                        "base_addr": f"0x{current_base:08X}",
                        "curve_addr": f"0x{current_base + args.curve_offset:08X}",
                        "spin_addr": f"0x{current_base + args.spin_offset:08X}",
                        "curve": curve,
                        "spin": spin,
                        "curve_max": cmax,
                        "spin_max": smax,
                        "curve_offset": args.curve_offset,
                        "spin_offset": args.spin_offset,
                        "curve_max_offset": args.curve_max_offset,
                        "spin_max_offset": args.spin_max_offset,
                        "rescan_count": rescan_count,
                    }
                    write_json(json_path, payload)

                    print_tuple = (current_base, round(curve, 4), round(spin, 4), round(cmax, 4), round(smax, 4), rescan_count)
                    if (not args.print_only_changed) or print_tuple != last_print_tuple:
                        print(f"[LIVE] base=0x{current_base:08X} curve={fmt_f(curve)}/{fmt_f(cmax)} spin={fmt_f(spin)}/{fmt_f(smax)} rescans={rescan_count}")
                        last_print_tuple = print_tuple
                else:
                    invalid_count += 1
                    row.update({
                        "ok": False,
                        "reason": reason,
                        "base": f"0x{current_base:08X}",
                        "rescan_count": rescan_count,
                    })
                    payload = {
                        "ok": False,
                        "reason": reason,
                        "source": "spin_curve_live_rescan",
                        "time": now,
                        "base_addr": f"0x{current_base:08X}",
                        "invalid_count": invalid_count,
                        "rescan_count": rescan_count,
                    }
                    write_json(json_path, payload)
                    if invalid_count >= args.invalid_threshold and time.time() - last_rescan >= args.rescan_cooldown:
                        print(f"[INVALID] base=0x{current_base:08X}, reason={reason}, invalid_count={invalid_count}. rescan...")
                        current_base, cand_count, selected_score = do_rescan(reason)
                        invalid_count = 0
                        last_print_tuple = None

                w.writerow(row)
                f.flush()
                time.sleep(args.interval)

    except KeyboardInterrupt:
        print("\n[INFO] Ctrl+C")
    finally:
        try:
            kernel32.CloseHandle(hproc)
        except Exception:
            pass
        print(f"[DONE] csv={csv_path}")
        print(f"[DONE] json={json_path.resolve()}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        raise
