# -*- coding: utf-8 -*-
"""
pangya_memory_probe_with_distance_final.py

ProjectG127.exe 로컬/개인 분석용 메모리 프로브.
현재 확인된 고저차 접근 코드:
    ProjectG127.exe + 0x12D6C1
    0052D6C1: fld dword ptr [esi+34]
    0052D6C4: fstp dword ptr [ebp-38]

동작:
    1) ProjectG127.exe 프로세스에 attach
    2) 위 코드 위치에 짧은 JMP hook 설치
    3) hook 실행 시 현재 ESI 값을 remote storage에 저장
    4) Python에서 [saved_esi + 0x34] float를 읽어 고저차로 반환

주의:
    - 공개/온라인 서버가 아니라 본인 로컬 클라이언트 분석용으로만 사용하세요.
    - CE Auto Assemble을 Python으로 옮긴 테스트 코드입니다.
    - hook 설치 중 게임이 크래시될 수 있으니 원본 exe/세이브를 백업하고 테스트하세요.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import struct
import time
from dataclasses import dataclass
from typing import Optional

try:
    import psutil
except Exception:
    psutil = None


kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

# ---------------------------------------------------------------------
# WinAPI constants
# ---------------------------------------------------------------------
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
PAGE_EXECUTE_READWRITE = 0x40
PAGE_READWRITE = 0x04

TH32CS_SNAPMODULE = 0x00000008
TH32CS_SNAPMODULE32 = 0x00000010
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value


# ---------------------------------------------------------------------
# WinAPI prototypes
# ---------------------------------------------------------------------
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


class MemoryProbeError(RuntimeError):
    pass


def _last_error(prefix: str) -> MemoryProbeError:
    return MemoryProbeError(f"{prefix}. GetLastError={ctypes.get_last_error()}")


def _pack_rel32(src_addr: int, dst_addr: int) -> bytes:
    """
    x86 JMP/CALL rel32용 상대값.
    src_addr는 rel32 명령 시작 주소, dst_addr는 목적지 주소.
    """
    rel = dst_addr - (src_addr + 5)
    if not -0x80000000 <= rel <= 0x7FFFFFFF:
        raise MemoryProbeError(f"rel32 range overflow: src=0x{src_addr:X}, dst=0x{dst_addr:X}, rel={rel}")
    return struct.pack("<i", rel)


def find_pid_by_name(process_name: str) -> Optional[int]:
    if psutil is None:
        raise MemoryProbeError("psutil이 필요합니다. pip install psutil")

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
        raise _last_error("CreateToolhelp32Snapshot 실패")

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

        raise MemoryProbeError(f"모듈을 찾지 못했습니다: {module_name}")
    finally:
        kernel32.CloseHandle(snap)



# ---------------------------------------------------------------------
# tiny x86 instruction length helper
# ---------------------------------------------------------------------
def _x86_modrm_instruction_length(data: bytes, start: int = 0) -> int:
    """
    매우 작은 x86 length decoder.
    현재 목적은 CE에서 찾은 FPU 명령(D9/D8 xx disp8 등) 뒤에 이어지는
    다음 명령까지 통째로 훔쳐서 5바이트 JMP 패치 크기를 맞추는 것이다.

    완전한 디스어셈블러가 아니므로, distance hook 위치에서 예외가 나면
    CE Memory Viewer에서 0052DF5C 주변 바이트를 확인해서 고정 original bytes로 바꿔야 한다.
    """
    i = start
    n = len(data)

    # prefixes
    while i < n and data[i] in (0x66, 0x67, 0xF2, 0xF3, 0x26, 0x2E, 0x36, 0x3E, 0x64, 0x65):
        i += 1

    if i >= n:
        return 1

    op = data[i]
    i += 1

    # simple one-byte opcodes without modrm commonly seen nearby
    if op in (0x90, 0xC3, 0xCC, 0x9B):
        return i - start

    # rel32 call/jmp, short jmp/jcc. We do not want to relocate these blindly.
    if op in (0xE8, 0xE9):
        return i - start + 4
    if op in range(0x70, 0x80) or op == 0xEB:
        return i - start + 1

    # push/pop reg
    if 0x50 <= op <= 0x5F:
        return i - start

    # immediate mov reg, imm32
    if 0xB8 <= op <= 0xBF:
        return i - start + 4

    # common immediate group with modrm + imm8/imm32
    imm_after_modrm = 0
    if op in (0x80, 0x82, 0x83, 0xC6):
        imm_after_modrm = 1
    elif op in (0x81, 0xC7):
        imm_after_modrm = 4

    # opcodes that use modrm in this project's hook areas
    uses_modrm = (
        op in (0xD8, 0xD9, 0xDA, 0xDB, 0xDC, 0xDD, 0xDE, 0xDF,  # x87
               0x8B, 0x89, 0x8D, 0x88, 0x8A, 0x39, 0x3B, 0x01, 0x03,
               0x29, 0x2B, 0x85, 0x8F, 0xFF)
        or imm_after_modrm > 0
    )

    if not uses_modrm:
        # fallback: assume 1-byte instruction
        return i - start

    if i >= n:
        return i - start

    modrm = data[i]
    i += 1
    mod = (modrm >> 6) & 3
    rm = modrm & 7

    # SIB byte in 32-bit addressing when rm=4 and mod != 3
    if mod != 3 and rm == 4:
        if i >= n:
            return i - start
        sib = data[i]
        i += 1
        base = sib & 7
        if mod == 0 and base == 5:
            i += 4
    elif mod == 0 and rm == 5:
        i += 4

    if mod == 1:
        i += 1
    elif mod == 2:
        i += 4

    i += imm_after_modrm
    return i - start


def _calc_stolen_len(data: bytes, min_len: int = 5) -> int:
    total = 0
    while total < min_len:
        total += _x86_modrm_instruction_length(data, total)
        if total > len(data):
            raise MemoryProbeError("instruction length decode overflow")
    return total


@dataclass
class HookInfo:
    hook_addr: int
    cave_addr: int
    storage_addr: int
    original_bytes: bytes
    installed: bool = False


class PangyaMemoryProbe:
    """
    ProjectG127.exe 메모리 후킹/읽기 테스트 클래스.

    현재 지원:
        - 고저차 height: hook으로 저장한 ESI + 0x34 float
        - 실시간 남은거리 distance_live: hook으로 저장한 EDI + 0x4C float
        - 최종/표시 남은거리 distance_final: hook으로 저장한 ESI + 0x2C float
    """

    # 0052D6C1 - D9 46 34      - fld dword ptr [esi+34]
    # 0052D6C4 - D9 5D C8      - fstp dword ptr [ebp-38]
    # 두 명령 6바이트를 JMP로 대체하고 cave에서 원래 명령 재실행 후 0052D6C7로 복귀한다.
    IMAGE_BASE_DEFAULT = 0x00400000
    HEIGHT_HOOK_RVA = 0x0052D6C1 - IMAGE_BASE_DEFAULT
    HEIGHT_ORIGINAL = bytes.fromhex("D9 46 34 D9 5D C8")
    HEIGHT_RETURN_DELTA = len(HEIGHT_ORIGINAL)
    HEIGHT_OFFSET = 0x34

    # 0052DF5C - D9 5F 4C      - fstp dword ptr [edi+4C]
    # distance_live 후보: 현재 EDI + 0x4C 에 실시간 남은거리 float를 쓴다.
    # 이 위치는 뒤 명령 길이를 런타임에 계산해 5바이트 JMP 패치가 가능한 만큼 훔친다.
    DISTANCE_HOOK_RVA = 0x0052DF5C - IMAGE_BASE_DEFAULT
    DISTANCE_FIRST_BYTES = bytes.fromhex("D9 5F 4C")
    DISTANCE_OFFSET = 0x4C

    # 005341EF - D9 56 2C      - fst dword ptr [esi+2C]
    # distance_final/표시 캐시 후보: 현재 ESI + 0x2C 에 남은거리 float를 쓴다.
    # 사용자가 확인한 1FBBB01C 계열 주소. 보통 착지/도착/표시 갱신 시점에 반응한다.
    DISTANCE_FINAL_HOOK_RVA = 0x005341EF - IMAGE_BASE_DEFAULT
    DISTANCE_FINAL_FIRST_BYTES = bytes.fromhex("D9 56 2C")
    DISTANCE_FINAL_OFFSET = 0x2C

    def __init__(self, process_name: str = "ProjectG127.exe"):
        self.process_name = process_name
        self.pid: Optional[int] = None
        self.handle: Optional[int] = None
        self.module_base: Optional[int] = None
        self.height_hook: Optional[HookInfo] = None
        self.distance_hook: Optional[HookInfo] = None
        self.distance_final_hook: Optional[HookInfo] = None

    # -------------------------
    # lifecycle
    # -------------------------
    def attach(self) -> None:
        pid = find_pid_by_name(self.process_name)
        if pid is None:
            raise MemoryProbeError(f"프로세스를 찾지 못했습니다: {self.process_name}")

        handle = kernel32.OpenProcess(PROCESS_ALL_NEEDED, False, pid)
        if not handle:
            raise _last_error("OpenProcess 실패. 관리자 권한으로 실행했는지 확인하세요")

        self.pid = pid
        self.handle = handle
        self.module_base = get_module_base(pid, self.process_name)

    def close(self) -> None:
        try:
            self.uninstall_distance_final_hook()
        except Exception:
            pass

        try:
            self.uninstall_distance_hook()
        except Exception:
            pass

        try:
            self.uninstall_height_hook()
        except Exception:
            pass

        if self.handle:
            kernel32.CloseHandle(self.handle)
            self.handle = None

    def __enter__(self) -> "PangyaMemoryProbe":
        self.attach()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def _require_attached(self) -> None:
        if not self.handle or self.pid is None or self.module_base is None:
            raise MemoryProbeError("먼저 attach()를 호출하세요.")

    # -------------------------
    # low-level memory I/O
    # -------------------------
    def read_bytes(self, addr: int, size: int) -> bytes:
        self._require_attached()
        buf = (ctypes.c_ubyte * size)()
        read = ctypes.c_size_t(0)
        ok = kernel32.ReadProcessMemory(self.handle, ctypes.c_void_p(addr), buf, size, ctypes.byref(read))
        if not ok or read.value != size:
            raise _last_error(f"ReadProcessMemory 실패: addr=0x{addr:X}, size={size}, read={read.value}")
        return bytes(buf)

    def write_bytes(self, addr: int, data: bytes) -> None:
        self._require_attached()
        written = ctypes.c_size_t(0)
        src = ctypes.create_string_buffer(data)
        old = wt.DWORD(0)

        if not kernel32.VirtualProtectEx(self.handle, ctypes.c_void_p(addr), len(data), PAGE_EXECUTE_READWRITE, ctypes.byref(old)):
            raise _last_error(f"VirtualProtectEx 실패: addr=0x{addr:X}")

        try:
            ok = kernel32.WriteProcessMemory(self.handle, ctypes.c_void_p(addr), src, len(data), ctypes.byref(written))
            if not ok or written.value != len(data):
                raise _last_error(f"WriteProcessMemory 실패: addr=0x{addr:X}, size={len(data)}, written={written.value}")
            kernel32.FlushInstructionCache(self.handle, ctypes.c_void_p(addr), len(data))
        finally:
            tmp = wt.DWORD(0)
            kernel32.VirtualProtectEx(self.handle, ctypes.c_void_p(addr), len(data), old.value, ctypes.byref(tmp))

    def read_u32(self, addr: int) -> int:
        return struct.unpack("<I", self.read_bytes(addr, 4))[0]

    def read_float(self, addr: int) -> float:
        return struct.unpack("<f", self.read_bytes(addr, 4))[0]

    def alloc_executable(self, size: int = 4096) -> int:
        self._require_attached()
        addr = kernel32.VirtualAllocEx(
            self.handle,
            None,
            size,
            MEM_COMMIT | MEM_RESERVE,
            PAGE_EXECUTE_READWRITE,
        )
        if not addr:
            raise _last_error("VirtualAllocEx 실패")
        return int(addr)

    # -------------------------
    # height hook
    # -------------------------
    def install_height_hook(self, *, force: bool = False) -> HookInfo:
        self._require_attached()
        assert self.module_base is not None

        hook_addr = self.module_base + self.HEIGHT_HOOK_RVA
        current = self.read_bytes(hook_addr, len(self.HEIGHT_ORIGINAL))

        if current != self.HEIGHT_ORIGINAL:
            # 이미 JMP 후킹되어 있거나, 클라이언트 버전/패치가 다른 경우
            if current[:1] == b"\xE9" and self.height_hook is not None:
                return self.height_hook
            if not force:
                raise MemoryProbeError(
                    "고저차 hook 위치의 원본 바이트가 예상과 다릅니다.\n"
                    f"hook_addr=0x{hook_addr:X}\n"
                    f"expected={self.HEIGHT_ORIGINAL.hex(' ').upper()}\n"
                    f"current ={current.hex(' ').upper()}\n"
                    "CE에서 0052D6C1 주변 원본 바이트가 D9 46 34 D9 5D C8인지 확인하세요."
                )

        cave = self.alloc_executable(4096)
        storage = cave + 0x200
        return_addr = hook_addr + self.HEIGHT_RETURN_DELTA

        # newmem:
        #   mov [storage], esi       ; 89 35 imm32
        #   fld dword ptr [esi+34]   ; D9 46 34
        #   fstp dword ptr [ebp-38]  ; D9 5D C8
        #   jmp return_addr          ; E9 rel32
        code = bytearray()
        code += b"\x89\x35" + struct.pack("<I", storage)
        code += self.HEIGHT_ORIGINAL
        jmp_back_src = cave + len(code)
        code += b"\xE9" + _pack_rel32(jmp_back_src, return_addr)

        self.write_bytes(cave, bytes(code))
        self.write_bytes(storage, b"\x00\x00\x00\x00")

        # hook:
        #   jmp cave
        #   nop
        patch = b"\xE9" + _pack_rel32(hook_addr, cave) + b"\x90"
        self.write_bytes(hook_addr, patch)

        self.height_hook = HookInfo(
            hook_addr=hook_addr,
            cave_addr=cave,
            storage_addr=storage,
            original_bytes=current,
            installed=True,
        )
        return self.height_hook

    def uninstall_height_hook(self) -> None:
        if not self.height_hook or not self.height_hook.installed:
            return
        try:
            self.write_bytes(self.height_hook.hook_addr, self.height_hook.original_bytes)
        finally:
            self.height_hook.installed = False

    def read_height_base(self) -> Optional[int]:
        if not self.height_hook or not self.height_hook.installed:
            return None
        base = self.read_u32(self.height_hook.storage_addr)
        if base == 0:
            return None
        return base

    def read_height(self) -> Optional[float]:
        base = self.read_height_base()
        if not base:
            return None
        value = self.read_float(base + self.HEIGHT_OFFSET)
        # 고저차가 말도 안 되는 값이면 아직 잘못 잡힌 것으로 취급
        if not -500.0 <= value <= 500.0:
            return None
        return value



    # -------------------------
    # distance_live hook
    # -------------------------
    def install_distance_hook(self, *, force: bool = False) -> HookInfo:
        """
        CE에서 확인한 실시간 남은거리 write 위치:
            0052DF5C - D9 5F 4C - fstp dword ptr [edi+4C]

        이 명령이 실행될 때 현재 EDI를 remote storage에 저장한다.
        이후 read_distance_live()는 [saved_edi + 0x4C] float를 읽는다.
        """
        self._require_attached()
        assert self.module_base is not None

        hook_addr = self.module_base + self.DISTANCE_HOOK_RVA
        preview = self.read_bytes(hook_addr, 16)

        if not preview.startswith(self.DISTANCE_FIRST_BYTES):
            if preview[:1] == b"\xE9" and self.distance_hook is not None:
                return self.distance_hook
            if not force:
                raise MemoryProbeError(
                    "남은거리 hook 위치의 시작 바이트가 예상과 다릅니다.\n"
                    f"hook_addr=0x{hook_addr:X}\n"
                    f"expected startswith={self.DISTANCE_FIRST_BYTES.hex(' ').upper()}\n"
                    f"current ={preview[:8].hex(' ').upper()}\n"
                    "CE에서 0052DF5C가 D9 5F 4C인지 확인하세요."
                )

        stolen_len = _calc_stolen_len(preview, 5)
        original = preview[:stolen_len]

        # 상대 call/jmp가 훔친 바이트에 들어가면 relocation이 필요하므로 중단한다.
        if any(b in original for b in (0xE8, 0xE9, 0xEB)):
            raise MemoryProbeError(
                "남은거리 hook stolen bytes에 상대 call/jmp가 포함되어 자동 relocation을 중단합니다.\n"
                f"hook_addr=0x{hook_addr:X}, stolen={original.hex(' ').upper()}"
            )

        cave = self.alloc_executable(4096)
        storage = cave + 0x200
        return_addr = hook_addr + stolen_len

        # newmem:
        #   mov [storage], edi       ; 89 3D imm32
        #   <stolen original bytes>  ; 원래 명령 실행
        #   jmp return_addr
        code = bytearray()
        code += b"\x89\x3D" + struct.pack("<I", storage)
        code += original
        jmp_back_src = cave + len(code)
        code += b"\xE9" + _pack_rel32(jmp_back_src, return_addr)

        self.write_bytes(cave, bytes(code))
        self.write_bytes(storage, b"\x00\x00\x00\x00")

        patch = b"\xE9" + _pack_rel32(hook_addr, cave)
        if stolen_len > 5:
            patch += b"\x90" * (stolen_len - 5)
        self.write_bytes(hook_addr, patch)

        self.distance_hook = HookInfo(
            hook_addr=hook_addr,
            cave_addr=cave,
            storage_addr=storage,
            original_bytes=original,
            installed=True,
        )
        return self.distance_hook

    def uninstall_distance_hook(self) -> None:
        if not self.distance_hook or not self.distance_hook.installed:
            return
        try:
            self.write_bytes(self.distance_hook.hook_addr, self.distance_hook.original_bytes)
        finally:
            self.distance_hook.installed = False

    def read_distance_base(self) -> Optional[int]:
        if not self.distance_hook or not self.distance_hook.installed:
            return None
        base = self.read_u32(self.distance_hook.storage_addr)
        if base == 0:
            return None
        return base

    def read_distance_live(self) -> Optional[float]:
        base = self.read_distance_base()
        if not base:
            return None
        value = self.read_float(base + self.DISTANCE_OFFSET)
        # 홀 거리로 보기 어려운 값이면 무시. 필요하면 범위는 넓혀도 됨.
        if not 0.0 <= value <= 2000.0:
            return None
        return value


    # -------------------------
    # distance_final/display-cache hook
    # -------------------------
    def install_distance_final_hook(self, *, force: bool = False) -> HookInfo:
        """
        CE에서 확인한 최종/표시 남은거리 write 위치:
            005341EF - D9 56 2C - fst dword ptr [esi+2C]

        이 명령이 실행될 때 현재 ESI를 remote storage에 저장한다.
        이후 read_distance_final()은 [saved_esi + 0x2C] float를 읽는다.

        주의:
            이 값은 실시간 이동 거리라기보다, 사용자가 확인한 것처럼
            착지/도착/표시 갱신 시점에만 갱신될 수 있다.
        """
        self._require_attached()
        assert self.module_base is not None

        hook_addr = self.module_base + self.DISTANCE_FINAL_HOOK_RVA
        preview = self.read_bytes(hook_addr, 16)

        if not preview.startswith(self.DISTANCE_FINAL_FIRST_BYTES):
            if preview[:1] == b"\xE9" and self.distance_final_hook is not None:
                return self.distance_final_hook
            if not force:
                raise MemoryProbeError(
                    "최종/표시 남은거리 hook 위치의 시작 바이트가 예상과 다릅니다.\n"
                    f"hook_addr=0x{hook_addr:X}\n"
                    f"expected startswith={self.DISTANCE_FINAL_FIRST_BYTES.hex(' ').upper()}\n"
                    f"current ={preview[:8].hex(' ').upper()}\n"
                    "CE에서 005341EF가 D9 56 2C인지 확인하세요."
                )

        stolen_len = _calc_stolen_len(preview, 5)
        original = preview[:stolen_len]

        if any(b in original for b in (0xE8, 0xE9, 0xEB)):
            raise MemoryProbeError(
                "최종/표시 남은거리 hook stolen bytes에 상대 call/jmp가 포함되어 자동 relocation을 중단합니다.\n"
                f"hook_addr=0x{hook_addr:X}, stolen={original.hex(' ').upper()}"
            )

        cave = self.alloc_executable(4096)
        storage = cave + 0x200
        return_addr = hook_addr + stolen_len

        # newmem:
        #   mov [storage], esi       ; 89 35 imm32
        #   <stolen original bytes>  ; 원래 명령 실행
        #   jmp return_addr
        code = bytearray()
        code += b"\x89\x35" + struct.pack("<I", storage)
        code += original
        jmp_back_src = cave + len(code)
        code += b"\xE9" + _pack_rel32(jmp_back_src, return_addr)

        self.write_bytes(cave, bytes(code))
        self.write_bytes(storage, b"\x00\x00\x00\x00")

        patch = b"\xE9" + _pack_rel32(hook_addr, cave)
        if stolen_len > 5:
            patch += b"\x90" * (stolen_len - 5)
        self.write_bytes(hook_addr, patch)

        self.distance_final_hook = HookInfo(
            hook_addr=hook_addr,
            cave_addr=cave,
            storage_addr=storage,
            original_bytes=original,
            installed=True,
        )
        return self.distance_final_hook

    def uninstall_distance_final_hook(self) -> None:
        if not self.distance_final_hook or not self.distance_final_hook.installed:
            return
        try:
            self.write_bytes(self.distance_final_hook.hook_addr, self.distance_final_hook.original_bytes)
        finally:
            self.distance_final_hook.installed = False

    def read_distance_final_base(self) -> Optional[int]:
        if not self.distance_final_hook or not self.distance_final_hook.installed:
            return None
        base = self.read_u32(self.distance_final_hook.storage_addr)
        if base == 0:
            return None
        return base

    def read_distance_final(self) -> Optional[float]:
        base = self.read_distance_final_base()
        if not base:
            return None
        value = self.read_float(base + self.DISTANCE_FINAL_OFFSET)
        if not 0.0 <= value <= 2000.0:
            return None
        return value

    def debug_info(self) -> str:
        parts = [
            f"pid={self.pid}",
            f"module_base=0x{self.module_base:X}" if self.module_base else "module_base=None",
        ]
        if self.height_hook:
            parts.extend([
                f"height_hook=0x{self.height_hook.hook_addr:X}",
                f"cave=0x{self.height_hook.cave_addr:X}",
                f"storage=0x{self.height_hook.storage_addr:X}",
            ])
        if self.distance_hook:
            parts.extend([
                f"distance_hook=0x{self.distance_hook.hook_addr:X}",
                f"distance_cave=0x{self.distance_hook.cave_addr:X}",
                f"distance_storage=0x{self.distance_hook.storage_addr:X}",
            ])
        if self.distance_final_hook:
            parts.extend([
                f"distance_final_hook=0x{self.distance_final_hook.hook_addr:X}",
                f"distance_final_cave=0x{self.distance_final_hook.cave_addr:X}",
                f"distance_final_storage=0x{self.distance_final_hook.storage_addr:X}",
            ])
        return ", ".join(parts)


def main() -> None:
    print("[INFO] ProjectG127.exe 고저차 hook 테스트")
    print("[INFO] 게임을 실행하고 샷 화면/고저차가 표시되는 상태에서 실행하세요.")

    probe = PangyaMemoryProbe("ProjectG127.exe")
    try:
        probe.attach()
        print(f"[INFO] attached: {probe.debug_info()}")

        hook = probe.install_height_hook()
        print(f"[INFO] height hook installed: hook=0x{hook.hook_addr:X}, storage=0x{hook.storage_addr:X}")

        distance_hook = probe.install_distance_hook()
        print(f"[INFO] distance_live hook installed: hook=0x{distance_hook.hook_addr:X}, storage=0x{distance_hook.storage_addr:X}")

        distance_final_hook = probe.install_distance_final_hook()
        print(f"[INFO] distance_final hook installed: hook=0x{distance_final_hook.hook_addr:X}, storage=0x{distance_final_hook.storage_addr:X}")

        print("[INFO] Ctrl+C로 종료합니다.")

        while True:
            h_base = probe.read_height_base()
            height = probe.read_height()
            d_base = probe.read_distance_base()
            distance = probe.read_distance_live()
            df_base = probe.read_distance_final_base()
            distance_final = probe.read_distance_final()

            h_base_text = "None" if h_base is None else f"0x{h_base:08X}"
            d_base_text = "None" if d_base is None else f"0x{d_base:08X}"
            df_base_text = "None" if df_base is None else f"0x{df_base:08X}"
            print(
                f"height_base={h_base_text}, height={height}, "
                f"distance_live_base={d_base_text}, distance_live={distance}, "
                f"distance_final_base={df_base_text}, distance_final={distance_final}"
            )
            time.sleep(0.5)

    except KeyboardInterrupt:
        print("\n[INFO] 종료 요청")
    finally:
        probe.close()
        print("[INFO] hook restored / closed")


if __name__ == "__main__":
    main()
