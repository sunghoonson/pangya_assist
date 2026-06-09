# patch_gameserver_build_all_clean_from_original.py
# 목적:
#   현재 GameServer-01.exe가 여러 실험 패치가 섞여 있을 수 있으므로,
#   깨끗한 원본 계열 exe(GameServer-02.exe 또는 GameServer-01.exe_ori)에서
#   "all 패치만" 다시 만든다.
#
# 적용하는 것:
#   1) gate_only
#      0x437020: cmp eax,1 -> cmp eax,0
#      0x437029: je -> nop nop
#
#   2) force_ready_shadow
#      0x43768F, 0x4377AA:
#      player flag 기반 계산 대신 room+4054C = 0x100 강제
#
# 적용하지 않는 것:
#   - 0x437320 remove 함수 stub
#   - 0x4374C0 vector decrement 제거
#   - 0x4375A2 empty finish return 변경
#   - 0x437F48 / 0x437F72 state6 packet 실험
#
# 사용 예:
#   python .\patch_gameserver_build_all_clean_from_original.py .\GameServer-02.exe
# 또는:
#   python .\patch_gameserver_build_all_clean_from_original.py .\GameServer-01.exe_ori
#
# 출력:
#   GameServer-02.all_clean.exe
#   또는 GameServer-01.exe_ori.all_clean.exe

from pathlib import Path
import struct
import sys
import shutil

IMAGE_BASE_DEFAULT = 0x00400000

PATCHES = [
    (
        0x00437020,
        bytes.fromhex("83 F8 01"),
        bytes.fromhex("83 F8 00"),
        "gate_only: cmp eax,1 -> cmp eax,0"
    ),
    (
        0x00437029,
        bytes.fromhex("74 27"),
        bytes.fromhex("90 90"),
        "gate_only: JE -> NOP NOP"
    ),
    (
        0x0043768F,
        bytes.fromhex("0F B6 46 08 83 E0 04 C1 E0 06 89 87 4C 05 04 00"),
        bytes.fromhex("B8 00 01 00 00 90 90 90 90 90 89 87 4C 05 04 00"),
        "force_ready_shadow main: room+4054C = 0x100"
    ),
    (
        0x004377AA,
        bytes.fromhex("0F B6 46 08 83 E0 04 C1 E0 06 89 87 4C 05 04 00"),
        bytes.fromhex("B8 00 01 00 00 90 90 90 90 90 89 87 4C 05 04 00"),
        "force_ready_shadow fallback: room+4054C = 0x100"
    ),
]

MUST_REMAIN_ORIGINAL = [
    (
        0x00437320,
        bytes.fromhex("55 8B EC 53 56 8B F1 57"),
        "remove player function prologue must be original, not stub"
    ),
    (
        0x004375A2,
        bytes.fromhex("B8 01 00 00 00"),
        "empty finish return must remain original for this baseline"
    ),
    (
        0x00437F4E,
        bytes.fromhex("0F 86 43 01 00 00"),
        "state6 count branch must remain original"
    ),
    (
        0x00437F72,
        bytes.fromhex("0F 95 C2"),
        "state6 index branch must remain original"
    ),
]

def parse_pe_sections(data: bytes):
    if data[:2] != b"MZ":
        raise ValueError("MZ header not found")

    pe_off = struct.unpack_from("<I", data, 0x3C)[0]
    if data[pe_off:pe_off + 4] != b"PE\0\0":
        raise ValueError("PE header not found")

    coff = pe_off + 4
    num_sections = struct.unpack_from("<H", data, coff + 2)[0]
    opt_size = struct.unpack_from("<H", data, coff + 16)[0]
    opt = coff + 20
    image_base = struct.unpack_from("<I", data, opt + 28)[0]

    sec_off = opt + opt_size
    sections = []
    for i in range(num_sections):
        o = sec_off + i * 40
        name = data[o:o+8].split(b"\0", 1)[0].decode("latin1", "replace")
        virtual_size, virtual_address, raw_size, raw_ptr = struct.unpack_from("<IIII", data, o + 8)
        sections.append((name, virtual_address, max(virtual_size, raw_size), raw_ptr))

    return image_base, sections

def va_to_off(va: int, image_base: int, sections):
    rva = va - image_base
    for name, sec_va, sec_size, raw_ptr in sections:
        if sec_va <= rva < sec_va + sec_size:
            return raw_ptr + (rva - sec_va)
    raise ValueError(f"VA not in sections: 0x{va:08X}")

def main():
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(2)

    src = Path(sys.argv[1])
    if not src.exists():
        print(f"[ERROR] source not found: {src}")
        sys.exit(1)

    data = bytearray(src.read_bytes())
    image_base, sections = parse_pe_sections(data)

    print(f"[INFO] source={src}")
    print(f"[INFO] image_base=0x{image_base:08X}")

    if image_base != IMAGE_BASE_DEFAULT:
        print(f"[WARN] unexpected image base: 0x{image_base:08X}")

    # 먼저 위험 패치가 없는 원본 계열인지 확인
    for va, expected, desc in MUST_REMAIN_ORIGINAL:
        off = va_to_off(va, image_base, sections)
        cur = bytes(data[off:off + len(expected)])
        print(f"[CHECK] 0x{va:08X} {desc}")
        print(f"        current : {cur.hex(' ').upper()}")
        print(f"        expected: {expected.hex(' ').upper()}")
        if cur != expected:
            print("[ERROR] 이 파일은 clean 원본 계열이 아닙니다.")
            print("        GameServer-02.exe 또는 GameServer-01.exe_ori 같은 원본 파일을 기준으로 다시 실행하세요.")
            sys.exit(3)

    # all patch 적용
    for va, old, new, desc in PATCHES:
        off = va_to_off(va, image_base, sections)
        cur = bytes(data[off:off + len(old)])
        print(f"[PATCH_CHECK] 0x{va:08X} {desc}")
        print(f"              current : {cur.hex(' ').upper()}")
        print(f"              expected: {old.hex(' ').upper()}")
        if cur == new:
            print("              already patched")
            continue
        if cur != old:
            print("[ERROR] expected bytes mismatch")
            sys.exit(4)
        data[off:off + len(old)] = new
        print("              patched")

    out = src.with_name(src.name + ".all_clean.exe")
    out.write_bytes(data)

    print(f"[DONE] output={out}")
    print("")
    print("다음 명령으로 교체:")
    print("  Copy-Item .\\" + out.name + " .\\GameServer-01.exe -Force")

if __name__ == "__main__":
    main()
