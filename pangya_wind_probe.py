# -*- coding: utf-8 -*-
"""
pangya_wind_probe.py

ProjectG127.exe 바람 후보 메모리 후킹/콘솔 로그 테스트.

목적:
    정적분석으로 찾은 바람 후보 함수 주변에 JMP hook을 걸고,
    실행 시점의 ECX/EDX 구조체 베이스를 저장한 뒤,
    base + offset 값을 Float로 읽어 콘솔에 출력한다.

후보:
    0080E4B8: fstp dword ptr [ecx+00000120]  ; wind direction 후보
    0080E4D0: fstp dword ptr [edx+0000011C]  ; wind power 후보
    0080E4EB: fstp dword ptr [ecx+00000134]  ; global wind x 후보
    0080E507: fstp dword ptr [ecx+00000138]  ; global wind y 후보
    0080E520: fstp dword ptr [ecx+0000013C]  ; global wind z 후보

사용:
    관리자 권한 PowerShell / VSCode 터미널에서:
        python .\pangya_wind_probe.py

주의:
    - 본인 로컬/개인 분석용으로만 사용하세요.
    - Cheat Engine 디버거를 동시에 attach한 상태에서는 충돌할 수 있습니다.
    - 게임이 크래시될 수 있으므로 테스트 전 클라이언트 백업을 권장합니다.
    - Ctrl+C로 종료하면 원본 바이트를 복구하려고 시도합니다.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import struct
import time
from dataclasses import dataclass
from typing import Optional, List

try:
    import psutil
except Exception:
    psutil = None


PROCESS_CREATE_THREAD = 0x0002
PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_VM_OPERATION = 0x0008
PROCESS_VM_WRITE = 0x0020
PROCESS_VM_READ = 0x0010
PROCESS_ALL_NEEDED = (
    PROCESS_CREATE_THREAD
    | PROCESS_QUERY_INFORMATION
    | PROCESS_VM_OPERATION
    | PROCESS_VM_WRITE
    | PROCESS_VM_READ
)

MEM_COMMIT = 0x1000
MEM_RESERVE = 0x2000
MEM_RELEASE = 0x8000
PAGE_EXECUTE_READWRITE = 0x40

TH32CS_SNAPMODULE = 0x00000008
TH32CS_SNAPMODULE32 = 0x00000010
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

kernel32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
kernel32.OpenProcess.restype = wt.HANDLE

kernel32.CloseHandle.argtypes = [wt.HANDLE]
kernel32.CloseHandle.restype = wt.BOOL

kernel32.ReadProcessMemory.argtypes = [wt.HANDLE, wt.LPCVOID, wt.LPVOID, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
kernel32.ReadProcessMemory.restype = wt.BOOL

kernel32.WriteProcessMemory.argtypes = [wt.HANDLE, wt.LPVOID, wt.LPCVOID, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
kernel32.WriteProcessMemory.restype = wt.BOOL

kernel32.VirtualAllocEx.argtypes = [wt.HANDLE, wt.LPVOID, ctypes.c_size_t, wt.DWORD, wt.DWORD]
kernel32.VirtualAllocEx.restype = wt.LPVOID

kernel32.VirtualFreeEx.argtypes = [wt.HANDLE, wt.LPVOID, ctypes.c_size_t, wt.DWORD]
kernel32.VirtualFreeEx.restype = wt.BOOL

kernel32.VirtualProtectEx.argtypes = [wt.HANDLE, wt.LPVOID, ctypes.c_size_t, wt.DWORD, ctypes.POINTER(wt.DWORD)]
kernel32.VirtualProtectEx.restype = wt.BOOL

kernel32.FlushInstructionCache.argtypes = [wt.HANDLE, wt.LPCVOID, ctypes.c_size_t]
kernel32.FlushInstructionCache.restype = wt.BOOL

kernel32.CreateToolhelp32Snapshot.argtypes = [wt.DWORD, wt.DWORD]
kernel32.CreateToolhelp32Snapshot.restype = wt.HANDLE


class MODULEENTRY32(ctypes.Structure):
    _fields_ = [
        ("dwSize", wt.DWORD),
        ("th32ModuleID", wt.DWORD),
        ("th32ProcessID", wt.DWORD),
        ("GlblcntUsage", wt.DWORD),
        ("ProccntUsage", wt.DWORD),
        ("modBaseAddr", ctypes.POINTER(ctypes.c_ubyte)),
        ("modBaseSize", wt.DWORD),
        ("hModule", wt.HMODULE),
        ("szModule", ctypes.c_char * 256),
        ("szExePath", ctypes.c_char * 260),
    ]


kernel32.Module32First.argtypes = [wt.HANDLE, ctypes.POINTER(MODULEENTRY32)]
kernel32.Module32First.restype = wt.BOOL
kernel32.Module32Next.argtypes = [wt.HANDLE, ctypes.POINTER(MODULEENTRY32)]
kernel32.Module32Next.restype = wt.BOOL


class WindProbeError(RuntimeError):
    pass


def last_error(prefix: str) -> WindProbeError:
    return WindProbeError(f"{prefix}. GetLastError={ctypes.get_last_error()}")


def pack_rel32(src_addr: int, dst_addr: int) -> bytes:
    rel = dst_addr - (src_addr + 5)
    if not -0x80000000 <= rel <= 0x7FFFFFFF:
        raise WindProbeError(f"rel32 overflow: src=0x{src_addr:X}, dst=0x{dst_addr:X}, rel={rel}")
    return struct.pack("<i", rel)


def find_pid_by_name(process_name: str) -> Optional[int]:
    if psutil is None:
        raise WindProbeError("psutil이 필요합니다. pip install psutil")

    target = process_name.lower()
    for proc in psutil.process_iter(["pid", "name"]):
        try:
            if (proc.info.get("name") or "").lower() == target:
                return int(proc.info["pid"])
        except Exception:
            continue
    return None


def get_module_base(pid: int, module_name: str) -> int:
    snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPMODULE | TH32CS_SNAPMODULE32, pid)
    if snap == INVALID_HANDLE_VALUE:
        raise last_error("CreateToolhelp32Snapshot 실패")

    try:
        me32 = MODULEENTRY32()
        me32.dwSize = ctypes.sizeof(MODULEENTRY32)
        ok = kernel32.Module32First(snap, ctypes.byref(me32))
        target = module_name.lower().encode("mbcs", errors="ignore")

        while ok:
            name = bytes(me32.szModule).split(b"\x00", 1)[0].lower()
            if name == target:
                return ctypes.addressof(me32.modBaseAddr.contents)
            ok = kernel32.Module32Next(snap, ctypes.byref(me32))

        raise WindProbeError(f"모듈을 찾지 못했습니다: {module_name}")
    finally:
        kernel32.CloseHandle(snap)


@dataclass
class HookSpec:
    name: str
    va: int
    expected: bytes
    base_reg: str
    value_offset: int


@dataclass
class InstalledHook:
    spec: HookSpec
    hook_addr: int
    cave_addr: int
    storage_addr: int
    original_bytes: bytes
    installed: bool = False


class PangyaWindProbe:
    IMAGE_BASE_DEFAULT = 0x00400000

    # 정적분석 후보. VA 기준.
    HOOK_SPECS: List[HookSpec] = [
        HookSpec(
            name="wind_dir",
            va=0x0080E4B8,
            expected=bytes.fromhex("D9 99 20 01 00 00"),  # fstp dword ptr [ecx+120]
            base_reg="ecx",
            value_offset=0x120,
        ),
        HookSpec(
            name="wind_power",
            va=0x0080E4D0,
            expected=bytes.fromhex("D9 9A 1C 01 00 00"),  # fstp dword ptr [edx+11C]
            base_reg="edx",
            value_offset=0x11C,
        ),
        HookSpec(
            name="global_wind_x",
            va=0x0080E4EB,
            expected=bytes.fromhex("D9 99 34 01 00 00"),  # fstp dword ptr [ecx+134]
            base_reg="ecx",
            value_offset=0x134,
        ),
        HookSpec(
            name="global_wind_y",
            va=0x0080E507,
            expected=bytes.fromhex("D9 99 38 01 00 00"),  # fstp dword ptr [ecx+138]
            base_reg="ecx",
            value_offset=0x138,
        ),
        HookSpec(
            name="global_wind_z",
            va=0x0080E520,
            expected=bytes.fromhex("D9 99 3C 01 00 00"),  # fstp dword ptr [ecx+13C]
            base_reg="ecx",
            value_offset=0x13C,
        ),
    ]

    def __init__(self, process_name: str = "ProjectG127.exe"):
        self.process_name = process_name
        self.pid: Optional[int] = None
        self.handle: Optional[int] = None
        self.module_base: Optional[int] = None
        self.hooks: List[InstalledHook] = []

    def attach(self) -> None:
        pid = find_pid_by_name(self.process_name)
        if pid is None:
            raise WindProbeError(f"프로세스를 찾지 못했습니다: {self.process_name}")

        handle = kernel32.OpenProcess(PROCESS_ALL_NEEDED, False, pid)
        if not handle:
            raise last_error("OpenProcess 실패. 관리자 권한으로 실행했는지 확인하세요")

        self.pid = pid
        self.handle = handle
        self.module_base = get_module_base(pid, self.process_name)

        print(f"[INFO] attached pid={pid}")
        print(f"[INFO] module_base=0x{self.module_base:08X}")

    def close(self) -> None:
        self.uninstall_all_hooks()

        if self.handle:
            kernel32.CloseHandle(self.handle)
            self.handle = None

    def require_attached(self) -> None:
        if not self.handle or self.pid is None or self.module_base is None:
            raise WindProbeError("먼저 attach()를 호출하세요.")

    def addr_from_va(self, va: int) -> int:
        self.require_attached()
        assert self.module_base is not None
        rva = va - self.IMAGE_BASE_DEFAULT
        return self.module_base + rva

    def read_bytes(self, addr: int, size: int) -> bytes:
        self.require_attached()
        buf = (ctypes.c_ubyte * size)()
        read = ctypes.c_size_t(0)
        ok = kernel32.ReadProcessMemory(self.handle, ctypes.c_void_p(addr), buf, size, ctypes.byref(read))
        if not ok or read.value != size:
            raise last_error(f"ReadProcessMemory 실패: addr=0x{addr:X}, size={size}, read={read.value}")
        return bytes(buf)

    def write_bytes(self, addr: int, data: bytes) -> None:
        self.require_attached()
        written = ctypes.c_size_t(0)
        src = ctypes.create_string_buffer(data)
        old = wt.DWORD(0)

        if not kernel32.VirtualProtectEx(self.handle, ctypes.c_void_p(addr), len(data), PAGE_EXECUTE_READWRITE, ctypes.byref(old)):
            raise last_error(f"VirtualProtectEx 실패: addr=0x{addr:X}")

        try:
            ok = kernel32.WriteProcessMemory(self.handle, ctypes.c_void_p(addr), src, len(data), ctypes.byref(written))
            if not ok or written.value != len(data):
                raise last_error(f"WriteProcessMemory 실패: addr=0x{addr:X}, size={len(data)}, written={written.value}")
            kernel32.FlushInstructionCache(self.handle, ctypes.c_void_p(addr), len(data))
        finally:
            tmp = wt.DWORD(0)
            kernel32.VirtualProtectEx(self.handle, ctypes.c_void_p(addr), len(data), old.value, ctypes.byref(tmp))

    def read_u32(self, addr: int) -> int:
        return struct.unpack("<I", self.read_bytes(addr, 4))[0]

    def read_float(self, addr: int) -> float:
        return struct.unpack("<f", self.read_bytes(addr, 4))[0]

    def alloc_executable(self, size: int = 4096) -> int:
        self.require_attached()
        addr = kernel32.VirtualAllocEx(
            self.handle,
            None,
            size,
            MEM_COMMIT | MEM_RESERVE,
            PAGE_EXECUTE_READWRITE,
        )
        if not addr:
            raise last_error("VirtualAllocEx 실패")
        return int(addr)

    def install_hook(self, spec: HookSpec, *, force: bool = False) -> InstalledHook:
        hook_addr = self.addr_from_va(spec.va)
        current = self.read_bytes(hook_addr, len(spec.expected))

        print(f"[CHECK] {spec.name} VA=0x{spec.va:08X} runtime=0x{hook_addr:08X}")
        print(f"        current : {current.hex(' ').upper()}")
        print(f"        expected: {spec.expected.hex(' ').upper()}")

        if current != spec.expected:
            if current[:1] == b"\xE9":
                raise WindProbeError(f"{spec.name}: 이미 JMP hook이 걸려있는 것 같습니다.")
            if not force:
                raise WindProbeError(
                    f"{spec.name}: 원본 바이트가 예상과 다릅니다.\n"
                    f"VA=0x{spec.va:08X}, runtime=0x{hook_addr:08X}\n"
                    f"expected={spec.expected.hex(' ').upper()}\n"
                    f"current ={current.hex(' ').upper()}\n"
                    "클라이언트 버전/패치 차이일 수 있습니다. CE Memory Viewer에서 해당 주소 명령을 확인하세요."
                )

        cave = self.alloc_executable(4096)
        storage = cave + 0x300
        original = current
        return_addr = hook_addr + len(original)

        # newmem:
        #   mov [storage], ecx/edx
        #   original instruction
        #   jmp return_addr
        code = bytearray()

        if spec.base_reg.lower() == "ecx":
            # 89 0D imm32 = mov [imm32], ecx
            code += b"\x89\x0D" + struct.pack("<I", storage)
        elif spec.base_reg.lower() == "edx":
            # 89 15 imm32 = mov [imm32], edx
            code += b"\x89\x15" + struct.pack("<I", storage)
        else:
            raise WindProbeError(f"지원하지 않는 base_reg: {spec.base_reg}")

        code += original

        jmp_back_src = cave + len(code)
        code += b"\xE9" + pack_rel32(jmp_back_src, return_addr)

        self.write_bytes(cave, bytes(code))
        self.write_bytes(storage, b"\x00\x00\x00\x00")

        patch = b"\xE9" + pack_rel32(hook_addr, cave)
        if len(original) > 5:
            patch += b"\x90" * (len(original) - 5)

        self.write_bytes(hook_addr, patch)

        hook = InstalledHook(
            spec=spec,
            hook_addr=hook_addr,
            cave_addr=cave,
            storage_addr=storage,
            original_bytes=original,
            installed=True,
        )
        self.hooks.append(hook)

        print(f"[HOOKED] {spec.name}: cave=0x{cave:08X}, storage=0x{storage:08X}")
        return hook

    def install_all_hooks(self, *, force: bool = False) -> None:
        for spec in self.HOOK_SPECS:
            self.install_hook(spec, force=force)

    def uninstall_all_hooks(self) -> None:
        for hook in reversed(self.hooks):
            if not hook.installed:
                continue
            try:
                self.write_bytes(hook.hook_addr, hook.original_bytes)
                print(f"[RESTORED] {hook.spec.name} VA=0x{hook.spec.va:08X}")
            except Exception as e:
                print(f"[WARN] restore failed: {hook.spec.name}: {e}")
            finally:
                hook.installed = False

    def get_saved_base(self, hook: InstalledHook) -> Optional[int]:
        if not hook.installed:
            return None
        base = self.read_u32(hook.storage_addr)
        if base == 0:
            return None
        return base

    def read_hook_value(self, hook: InstalledHook) -> tuple[Optional[int], Optional[float]]:
        base = self.get_saved_base(hook)
        if not base:
            return None, None

        addr = base + hook.spec.value_offset
        try:
            value = self.read_float(addr)
        except Exception:
            return base, None

        # 너무 말이 안 되는 float는 None 처리하지 않고 그대로 보여준다.
        # 후보 검증 단계에서는 이상값도 의미가 있을 수 있다.
        return base, value

    def snapshot(self) -> dict:
        result = {}
        for hook in self.hooks:
            base, value = self.read_hook_value(hook)
            result[hook.spec.name] = {
                "base": base,
                "offset": hook.spec.value_offset,
                "value": value,
            }
        return result

    def print_snapshot(self) -> None:
        snap = self.snapshot()

        def fmt_base(v):
            return "-" if v is None else f"0x{v:08X}"

        def fmt_float(v):
            if v is None:
                return "-"
            return f"{v: .6f}"

        wp = snap.get("wind_power", {})
        wd = snap.get("wind_dir", {})
        wx = snap.get("global_wind_x", {})
        wy = snap.get("global_wind_y", {})
        wz = snap.get("global_wind_z", {})

        print(
            "[WIND] "
            f"power={fmt_float(wp.get('value'))} base={fmt_base(wp.get('base'))}+11C | "
            f"dir={fmt_float(wd.get('value'))} base={fmt_base(wd.get('base'))}+120 | "
            f"vec=({fmt_float(wx.get('value'))}, {fmt_float(wy.get('value'))}, {fmt_float(wz.get('value'))}) "
            f"vec_base=({fmt_base(wx.get('base'))}, {fmt_base(wy.get('base'))}, {fmt_base(wz.get('base'))})"
        )


def main() -> None:
    process_name = "ProjectG127.exe"

    print("========== Pangya Wind Probe ==========")
    print(f"[INFO] target={process_name}")
    print("[INFO] 관리자 권한으로 실행하세요.")
    print("[INFO] 게임 샷 화면/홀 진입 후 바람 갱신 시점에 값이 들어옵니다.")
    print("[INFO] 종료: Ctrl+C")
    print("=======================================")

    probe = PangyaWindProbe(process_name)

    try:
        probe.attach()
        probe.install_all_hooks(force=False)

        print("")
        print("[INFO] hook 설치 완료. 값 대기 중...")
        print("[INFO] 화면 바람세기/각도와 power/dir/vec 값을 비교하세요.")
        print("")

        while True:
            probe.print_snapshot()
            time.sleep(0.5)

    except KeyboardInterrupt:
        print("\n[INFO] Ctrl+C 감지. hook 복구 중...")

    except Exception as e:
        print(f"\n[ERROR] {e}")

    finally:
        try:
            probe.close()
        except Exception as e:
            print(f"[WARN] 종료/복구 중 오류: {e}")

        print("[DONE] 종료")


if __name__ == "__main__":
    main()
