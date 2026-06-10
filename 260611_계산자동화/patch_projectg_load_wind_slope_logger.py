# -*- coding: utf-8 -*-
"""
patch_projectg_load_wind_slope_logger.py

ProjectG127.exe의 EntryPoint를 패치해서 같은 폴더의 DLL 2개를
자동 LoadLibraryA 하게 만든다.

로드 대상:
  1) pangya_wind_logger.dll
  2) pangya_slope_logger.dll

이 방식은 별도 injector를 쓰는 방식이 아니라,
클라이언트 EXE 파일 자체의 EntryPoint를 code cave로 돌려서
EXE 시작 직후 LoadLibraryA를 호출하게 만드는 방식이다.

사용:
  python .\patch_projectg_load_wind_slope_logger.py .\ProjectG127.exe

출력:
  ProjectG127.wind_slope_logger_loader.exe

적용 예:
  Copy-Item .\ProjectG127.exe .\ProjectG127.exe.backup_before_wind_slope_logger -Force
  Copy-Item .\ProjectG127.wind_slope_logger_loader.exe .\ProjectG127.exe -Force

필수:
  pangya_wind_logger.dll
  pangya_slope_logger.dll

위 DLL 2개를 ProjectG127.exe와 같은 폴더에 둔다.

주의:
  - 가능하면 원본/기존 백업 EXE 기준으로 실행하는 것을 권장한다.
  - 이미 wind_logger_loader가 적용된 EXE에 다시 적용해도 동작할 가능성은 높지만,
    loader가 중첩될 수 있으므로 깔끔하게 하려면 backup_before_wind_logger 같은 백업본에서
    다시 wind+slope 통합 패치를 만드는 편이 좋다.
"""

from __future__ import annotations

from pathlib import Path
import shutil
import struct
import sys


DLL_NAMES = [
    b"pangya_wind_logger.dll\x00",
    b"pangya_slope_logger.dll\x00",
]


def u16(data, off):
    return struct.unpack_from("<H", data, off)[0]


def u32(data, off):
    return struct.unpack_from("<I", data, off)[0]


def w32(data, off, value):
    struct.pack_into("<I", data, off, value & 0xFFFFFFFF)


class PE:
    def __init__(self, data: bytearray):
        self.data = data

        if data[:2] != b"MZ":
            raise RuntimeError("MZ header not found")

        self.pe = u32(data, 0x3C)

        if data[self.pe:self.pe + 4] != b"PE\0\0":
            raise RuntimeError("PE header not found")

        self.coff = self.pe + 4
        self.machine = u16(data, self.coff)
        self.num_sections = u16(data, self.coff + 2)
        self.opt_size = u16(data, self.coff + 16)
        self.opt = self.coff + 20
        self.magic = u16(data, self.opt)

        if self.magic != 0x10B:
            raise RuntimeError("PE32 only supported")

        self.address_of_entry_point_off = self.opt + 16
        self.address_of_entry_point = u32(data, self.address_of_entry_point_off)
        self.image_base = u32(data, self.opt + 28)

        # OptionalHeader.DataDirectory[IMAGE_DIRECTORY_ENTRY_IMPORT]
        self.import_dir_rva = u32(data, self.opt + 96 + 8 * 1)
        self.import_dir_size = u32(data, self.opt + 96 + 8 * 1 + 4)

        self.sections = []

        sec_off = self.opt + self.opt_size

        for i in range(self.num_sections):
            o = sec_off + i * 40
            name = bytes(data[o:o + 8]).split(b"\0", 1)[0].decode("latin1", "replace")
            virtual_size, virtual_address, raw_size, raw_ptr = struct.unpack_from("<IIII", data, o + 8)
            characteristics = u32(data, o + 36)

            self.sections.append({
                "name": name,
                "va": virtual_address,
                "vs": virtual_size,
                "raw_size": raw_size,
                "raw_ptr": raw_ptr,
                "chars": characteristics,
            })

    def rva_to_off(self, rva: int) -> int:
        for s in self.sections:
            start = s["va"]
            size = max(s["vs"], s["raw_size"])

            if start <= rva < start + size:
                return s["raw_ptr"] + (rva - start)

        raise RuntimeError(f"RVA not in sections: 0x{rva:X}")

    def off_to_rva(self, off: int) -> int:
        for s in self.sections:
            start = s["raw_ptr"]
            end = start + s["raw_size"]

            if start <= off < end:
                return s["va"] + (off - start)

        raise RuntimeError(f"file offset not in sections: 0x{off:X}")

    def read_c_string_rva(self, rva: int) -> bytes:
        off = self.rva_to_off(rva)
        end = self.data.find(b"\x00", off)

        if end < 0:
            raise RuntimeError("unterminated string")

        return bytes(self.data[off:end])

    def find_import_iat_va(self, dll_name: str, func_name: str) -> int:
        target_dll = dll_name.lower().encode("ascii")
        target_func = func_name.encode("ascii")

        if self.import_dir_rva == 0:
            raise RuntimeError("import directory not found")

        desc_off = self.rva_to_off(self.import_dir_rva)
        idx = 0

        while True:
            o = desc_off + idx * 20
            original_first_thunk, time_date, forwarder, name_rva, first_thunk = struct.unpack_from("<IIIII", self.data, o)

            if original_first_thunk == 0 and name_rva == 0 and first_thunk == 0:
                break

            dll = self.read_c_string_rva(name_rva).lower()

            if dll == target_dll:
                thunk_rva = original_first_thunk or first_thunk
                thunk_off = self.rva_to_off(thunk_rva)
                iat_rva = first_thunk
                n = 0

                while True:
                    thunk = u32(self.data, thunk_off + n * 4)

                    if thunk == 0:
                        break

                    # ordinal import는 무시
                    if (thunk & 0x80000000) == 0:
                        name_off = self.rva_to_off(thunk)
                        name_end = self.data.find(b"\x00", name_off + 2)
                        name = bytes(self.data[name_off + 2:name_end])

                        if name == target_func:
                            return self.image_base + iat_rva + n * 4

                    n += 1

            idx += 1

        raise RuntimeError(f"import not found: {dll_name}!{func_name}")

    def find_code_cave(self, min_size: int = 1024) -> tuple[int, int]:
        """
        EntryPoint가 있는 실행 섹션 안에서 연속 0x00 cave를 찾는다.
        wind+slope 2개 DLL명과 로더 스텁을 넣어야 하므로 기존 512보다 넉넉하게 1024를 요구한다.
        """
        ep_rva = self.address_of_entry_point
        ep_sec = None

        for s in self.sections:
            if s["va"] <= ep_rva < s["va"] + max(s["vs"], s["raw_size"]):
                ep_sec = s
                break

        if ep_sec is None:
            raise RuntimeError("entry point section not found")

        start = ep_sec["raw_ptr"]
        end = ep_sec["raw_ptr"] + ep_sec["raw_size"]
        data = self.data

        i = start

        while i < end:
            j = data.find(b"\x00" * min_size, i, end)

            if j < 0:
                break

            # 너무 초반/헤더 근처는 피한다.
            if j > start + 0x1000:
                return j, self.off_to_rva(j)

            i = j + min_size

        raise RuntimeError("executable code cave not found")


def rel32(src_va: int, dst_va: int) -> bytes:
    rel = dst_va - (src_va + 5)

    if not -0x80000000 <= rel <= 0x7FFFFFFF:
        raise RuntimeError(f"rel32 overflow: src=0x{src_va:X}, dst=0x{dst_va:X}")

    return struct.pack("<i", rel)


def build_string_table(cave_va: int, string_area_offset: int = 0x100) -> tuple[bytes, list[int]]:
    """
    cave 내부에 DLL 문자열들을 연속으로 배치하고,
    각 문자열의 VA 목록을 반환한다.
    """
    blob = bytearray()
    addrs = []

    for dll_name in DLL_NAMES:
        # 4바이트 정렬
        while len(blob) % 4 != 0:
            blob += b"\x00"

        addrs.append(cave_va + string_area_offset + len(blob))
        blob += dll_name

    return bytes(blob), addrs


def main():
    if len(sys.argv) != 2:
        print(__doc__)
        raise SystemExit(2)

    src = Path(sys.argv[1])

    if not src.exists():
        print(f"[ERROR] source not found: {src}")
        raise SystemExit(1)

    data = bytearray(src.read_bytes())
    pe = PE(data)

    print(f"[INFO] source={src}")
    print(f"[INFO] image_base=0x{pe.image_base:08X}")
    print(f"[INFO] original_ep_rva=0x{pe.address_of_entry_point:08X}")
    print(f"[INFO] original_ep_va =0x{pe.image_base + pe.address_of_entry_point:08X}")

    loadlibrary_iat_va = pe.find_import_iat_va("kernel32.dll", "LoadLibraryA")
    print(f"[INFO] kernel32!LoadLibraryA IAT VA=0x{loadlibrary_iat_va:08X}")

    cave_off, cave_rva = pe.find_code_cave(1024)
    cave_va = pe.image_base + cave_rva

    print(f"[INFO] cave file+0x{cave_off:X}, rva=0x{cave_rva:08X}, va=0x{cave_va:08X}")

    original_ep_va = pe.image_base + pe.address_of_entry_point

    string_area_offset = 0x100
    string_blob, dll_str_vas = build_string_table(cave_va, string_area_offset)

    # x86 code:
    #   pushfd
    #   pushad
    #
    #   push wind_dll_str
    #   call dword ptr [LoadLibraryA_IAT]
    #
    #   push slope_dll_str
    #   call dword ptr [LoadLibraryA_IAT]
    #
    #   popad
    #   popfd
    #   jmp original_ep
    code = bytearray()
    code += b"\x9C"  # pushfd
    code += b"\x60"  # pushad

    for dll_name, dll_str_va in zip(DLL_NAMES, dll_str_vas):
        printable_name = dll_name.rstrip(b"\x00").decode("ascii", "replace")
        print(f"[INFO] will LoadLibraryA: {printable_name} at VA=0x{dll_str_va:08X}")

        code += b"\x68" + struct.pack("<I", dll_str_va)
        code += b"\xFF\x15" + struct.pack("<I", loadlibrary_iat_va)

    code += b"\x61"  # popad
    code += b"\x9D"  # popfd
    code += b"\xE9" + rel32(cave_va + len(code), original_ep_va)

    if len(code) > string_area_offset:
        raise RuntimeError(f"loader stub too large: {len(code)} > {string_area_offset}")

    patch_blob = bytes(code).ljust(string_area_offset, b"\x90") + string_blob

    data[cave_off:cave_off + len(patch_blob)] = patch_blob

    # AddressOfEntryPoint를 새 cave로 변경
    w32(data, pe.address_of_entry_point_off, cave_rva)

    backup = src.with_name(src.name + ".backup_before_wind_slope_logger_loader")

    if not backup.exists():
        shutil.copy2(src, backup)
        print(f"[INFO] backup created: {backup}")

    out = src.with_name(src.stem + ".wind_slope_logger_loader" + src.suffix)
    out.write_bytes(data)

    print(f"[DONE] output={out}")
    print("")
    print("적용 예:")
    print(f"  Copy-Item .\\{src.name} .\\{src.name}.backup_before_wind_slope_logger -Force")
    print(f"  Copy-Item .\\{out.name} .\\{src.name} -Force")
    print("")
    print("필수 배치:")
    print("  ProjectG127.exe와 같은 폴더에 아래 파일을 둔다.")
    print("  - pangya_wind_logger.dll")
    print("  - pangya_slope_logger.dll")
    print("")
    print("확인 로그:")
    print("  - logs\\pangya_wind_live.json")
    print("  - logs\\pangya_slope_live.json")


if __name__ == "__main__":
    main()
