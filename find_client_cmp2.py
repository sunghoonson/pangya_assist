from pathlib import Path

path = Path(r"C:\Pangya_US8JP\RELEASE SRV4\GameServer-01.exe")
data = path.read_bytes()

patterns = {
    b"\x83\xF8\x02": "cmp eax, 2",
    b"\x83\xF9\x02": "cmp ecx, 2",
    b"\x83\xFA\x02": "cmp edx, 2",
    b"\x83\xFB\x02": "cmp ebx, 2",
    b"\x83\xFE\x02": "cmp esi, 2",
    b"\x83\xFF\x02": "cmp edi, 2",
}

short_jcc = set(range(0x70, 0x80))

results = []

for i in range(len(data) - 16):
    for pat, asm in patterns.items():
        if data.startswith(pat, i):
            for j in range(i + len(pat), min(i + len(pat) + 12, len(data) - 2)):
                b = data[j]

                if b in short_jcc:
                    results.append((i, asm, j, data[i:j+8]))
                    break

                if b == 0x0F and 0x80 <= data[j + 1] <= 0x8F:
                    results.append((i, asm, j, data[i:j+10]))
                    break

print("candidate count:", len(results))

for off, asm, jcc_off, bytes_data in results:
    print(
        f"file_off=0x{off:X}, {asm}, "
        f"jcc_off=0x{jcc_off:X}, bytes={bytes_data.hex(' ')}"
    )