# patch_projectg_skip_single_player_abort_test.py
# 목적:
#   ProjectG127.exe 클라이언트에서 1P 대회/게임 로딩 후 즉시 결과/랭킹 화면으로 빠지는
#   클라이언트측 "1명일 때 강제 종료/결과 전환" 후보 분기를 우회한다.
#
# 정적분석 후보:
#   0x00694FA0 근처 함수
#
#   0x00694FE0: cmp DWORD PTR [global+0xFDEC], 1
#   0x00694FE7: jne 0x00695012
#   ...
#   0x00695009: push 0
#   0x0069500D: call 0x0067C400
#
# 해석:
#   global+0xFDEC는 클라이언트가 알고 있는 현재 방/게임 player_count로 보인다.
#   player_count == 1일 때 특정 game_type 예외가 아니면 0x67C400(결과/종료/상태전환 후보)을 호출한다.
#
# 테스트 패치:
#   0x00694FE7: JNE +0x29
#   를
#   0x00694FE7: JMP +0x29
#   로 변경한다.
#
# 의미:
#   player_count == 1이어도 이 자동 종료/결과 전환 후보 호출을 건너뛴다.
#
# 주의:
#   이 패치는 "결과화면 전체 차단"이 아니다.
#   player_count==1 조건에서만 실행되는 자동 abort/transition 후보를 skip한다.
#   정상 라운딩 종료 후 서버가 보내는 결과/정산 packet에 의한 결과화면은 다른 경로일 가능성이 높다.
#
# 사용:
#   python .\patch_projectg_skip_single_player_abort_test.py .\ProjectG127.exe
#
# 출력:
#   ProjectG127.skip_single_player_abort.exe
#
# 적용:
#   기존 클라이언트 exe 백업 후, 출력 파일을 실제 실행 파일명으로 교체해서 테스트한다.

from pathlib import Path
import struct
import sys
import shutil

IMAGE_BASE = 0x00400000

PATCHES = [
    (
        0x00694FE7,
        bytes.fromhex("75 29"),  # jne 0x695012
        bytes.fromhex("EB 29"),  # jmp 0x695012
        "skip client-side player_count==1 abort/result transition candidate"
    ),
]

# 기존 start button 패치가 들어가 있는지도 정보만 출력한다.
INFO_CHECKS = [
    (
        0x0051049A,
        bytes.fromhex("76 DB"),
        bytes.fromhex("72 DB"),
        "start button min players: JBE -> JB"
    ),
    (
        0x0051047D,
        bytes.fromhex("32 C0"),
        bytes.fromhex("B0 01"),
        "force start enable: XOR AL,AL -> MOV AL,1"
    ),
]

def parse_pe(data: bytes):
    if data[:2] != b"MZ":
        raise RuntimeError("not MZ")
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    if data[pe:pe+4] != b"PE\0\0":
        raise RuntimeError("not PE")

    coff = pe + 4
    nsec = struct.unpack_from("<H", data, coff+2)[0]
    opt_size = struct.unpack_from("<H", data, coff+16)[0]
    opt = coff + 20
    image_base = struct.unpack_from("<I", data, opt+28)[0]
    sec_off = opt + opt_size

    sections = []
    for i in range(nsec):
        o = sec_off + i * 40
        name = data[o:o+8].split(b"\0", 1)[0].decode("latin1", "replace")
        vs, va, raw_size, raw_ptr = struct.unpack_from("<IIII", data, o+8)
        sections.append((name, va, max(vs, raw_size), raw_ptr))
    return image_base, sections

def va_to_off(va, image_base, sections):
    rva = va - image_base
    for name, s_va, s_size, raw_ptr in sections:
        if s_va <= rva < s_va + s_size:
            return raw_ptr + (rva - s_va)
    raise RuntimeError(f"VA not found in sections: 0x{va:08X}")

def get(data, image_base, sections, va, n):
    off = va_to_off(va, image_base, sections)
    return off, bytes(data[off:off+n])

def main():
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(2)

    src = Path(sys.argv[1])
    if not src.exists():
        print(f"[ERROR] source not found: {src}")
        sys.exit(1)

    data = bytearray(src.read_bytes())
    image_base, sections = parse_pe(data)

    print(f"[INFO] source={src}")
    print(f"[INFO] image_base=0x{image_base:08X}")

    for va, original, patched, desc in INFO_CHECKS:
        off, cur = get(data, image_base, sections, va, len(original))
        print(f"[INFO_CHECK] 0x{va:08X} file+0x{off:X}: {desc}")
        print(f"             current : {cur.hex(' ').upper()}")
        if cur == original:
            print("             state   : original")
        elif cur == patched:
            print("             state   : already patched")
        else:
            print("             state   : unknown/different")

    backup = src.with_name(src.name + ".bak_skip_single_player_abort")
    if not backup.exists():
        shutil.copy2(src, backup)
        print(f"[INFO] backup created: {backup}")

    for va, old, new, desc in PATCHES:
        off, cur = get(data, image_base, sections, va, len(old))
        print(f"[PATCH_CHECK] 0x{va:08X} file+0x{off:X}: {desc}")
        print(f"              current : {cur.hex(' ').upper()}")
        print(f"              expected: {old.hex(' ').upper()}")
        print(f"              patched : {new.hex(' ').upper()}")

        if cur == new:
            print("              already patched")
            continue
        if cur != old:
            print("[ERROR] expected bytes mismatch. patch aborted.")
            sys.exit(3)

        data[off:off+len(old)] = new
        print("              patched")

    out = src.with_name(src.stem + ".skip_single_player_abort" + src.suffix)
    out.write_bytes(data)
    print(f"[DONE] output={out}")
    print("")
    print("교체 예:")
    print(f"  Copy-Item .\\{src.name} .\\{src.name}.backup_before_skip_single_player_abort -Force")
    print(f"  Copy-Item .\\{out.name} .\\{src.name} -Force")

if __name__ == "__main__":
    main()
