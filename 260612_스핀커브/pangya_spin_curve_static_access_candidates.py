# -*- coding: utf-8 -*-
"""
pangya_spin_curve_static_access_candidates.py

ProjectG127.exe 정적 스캔으로 spin/curve 구조체 접근 후보를 찾는 도구입니다.
외부 디버거 attach / hardware breakpoint를 쓰지 않으므로 클라이언트를 튕기지 않습니다.

찾는 구조:
    struct + 0x18 = curve
    struct + 0x1C = spin
    struct + 0x20 = curve_max
    struct + 0x24 = spin_max

사용 예:
    python pangya_spin_curve_static_access_candidates.py --exe "C:\Pangya_US8JP\RELEASE SRV4\@Client EXE\ProjectG127.exe"

결과:
    logs\spin_curve_static_candidates\spin_curve_static_candidates_YYYYMMDD_HHMMSS.csv
    logs\spin_curve_static_candidates\spin_curve_static_candidates_YYYYMMDD_HHMMSS.txt
"""

from __future__ import annotations

import argparse
import csv
import os
import struct
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple, Optional

REGS = ["eax", "ecx", "edx", "ebx", "esp", "ebp", "esi", "edi"]
TARGET_DISPS = {0x18: "curve", 0x1C: "spin", 0x20: "curve_max", 0x24: "spin_max"}

@dataclass
class Section:
    name: str
    vaddr: int
    vsize: int
    raw_ptr: int
    raw_size: int
    chars: int

@dataclass
class Hit:
    file_off: int
    va: int
    kind: str
    base_reg: str
    disp: int
    field: str
    size: int
    bytes_hex: str

@dataclass
class Cluster:
    key_va: int
    start_va: int
    end_va: int
    score: float
    base_reg: str
    hit_count: int
    fields: str
    kinds: str
    hit_lines: List[str]


def read_pe_sections(data: bytes) -> Tuple[int, List[Section]]:
    if data[:2] != b"MZ":
        raise ValueError("PE/MZ 파일이 아닙니다.")
    pe_off = struct.unpack_from("<I", data, 0x3C)[0]
    if data[pe_off:pe_off + 4] != b"PE\0\0":
        raise ValueError("PE 헤더를 찾지 못했습니다.")

    image_base = struct.unpack_from("<I", data, pe_off + 0x34)[0]
    num_sections = struct.unpack_from("<H", data, pe_off + 6)[0]
    opt_size = struct.unpack_from("<H", data, pe_off + 20)[0]
    sec_off = pe_off + 24 + opt_size

    sections: List[Section] = []
    for i in range(num_sections):
        off = sec_off + i * 40
        name = data[off:off + 8].split(b"\0", 1)[0].decode("ascii", "ignore") or f"sec{i}"
        vsize, vaddr, raw_size, raw_ptr = struct.unpack_from("<IIII", data, off + 8)
        chars = struct.unpack_from("<I", data, off + 36)[0]
        sections.append(Section(name, vaddr, vsize, raw_ptr, raw_size, chars))
    return image_base, sections


def off_to_va(off: int, image_base: int, sections: List[Section]) -> Optional[int]:
    for s in sections:
        if s.raw_ptr <= off < s.raw_ptr + max(s.raw_size, 1):
            return image_base + s.vaddr + (off - s.raw_ptr)
    return None


def is_code_section(s: Section) -> bool:
    # IMAGE_SCN_CNT_CODE 0x20 or executable 0x20000000
    return bool(s.chars & 0x20) or bool(s.chars & 0x20000000)


def find_patterns(data: bytes, image_base: int, sections: List[Section]) -> List[Hit]:
    patterns: List[Tuple[bytes, str, str, int, int]] = []
    # tuple: pattern, kind, base_reg, disp, instr_size

    # x87 fld/fst/fstp m32real [reg+disp8]
    for rm, base_reg in enumerate(REGS):
        if base_reg == "esp":
            continue  # SIB 케이스는 여기서 제외
        for op, kind in [(0, "x87_fld"), (2, "x87_fst"), (3, "x87_fstp")]:
            modrm = 0x40 + op * 8 + rm
            for disp in TARGET_DISPS:
                patterns.append((bytes([0xD9, modrm, disp]), kind, base_reg, disp, 3))

    # SSE movss load/store [reg+disp8]
    for opcode, kind in [(0x10, "sse_movss_load"), (0x11, "sse_movss_store")]:
        for xmm in range(8):
            for rm, base_reg in enumerate(REGS):
                if base_reg == "esp":
                    continue
                modrm = 0x40 + xmm * 8 + rm
                for disp in TARGET_DISPS:
                    patterns.append((bytes([0xF3, 0x0F, opcode, modrm, disp]), kind, base_reg, disp, 5))

    # 일반 mov load/store [reg+disp8]
    for opcode, kind in [(0x8B, "mov_load"), (0x89, "mov_store")]:
        for regop in range(8):
            for rm, base_reg in enumerate(REGS):
                if base_reg == "esp":
                    continue
                modrm = 0x40 + regop * 8 + rm
                for disp in TARGET_DISPS:
                    patterns.append((bytes([opcode, modrm, disp]), kind, base_reg, disp, 3))

    hits: List[Hit] = []
    for sec in sections:
        if not is_code_section(sec):
            continue
        start = sec.raw_ptr
        end = min(len(data), sec.raw_ptr + sec.raw_size)
        if start < 0 or start >= len(data):
            continue
        sec_bytes = data[start:end]
        for pat, kind, base_reg, disp, instr_size in patterns:
            pos = 0
            while True:
                idx = sec_bytes.find(pat, pos)
                if idx < 0:
                    break
                file_off = start + idx
                va = off_to_va(file_off, image_base, sections)
                if va is not None:
                    hits.append(Hit(
                        file_off=file_off,
                        va=va,
                        kind=kind,
                        base_reg=base_reg,
                        disp=disp,
                        field=TARGET_DISPS[disp],
                        size=instr_size,
                        bytes_hex=pat.hex(" ").upper(),
                    ))
                pos = idx + 1
    hits.sort(key=lambda h: h.va)
    return hits


def make_clusters(hits: List[Hit], window: int = 96) -> List[Cluster]:
    clusters: List[Cluster] = []
    by_reg: Dict[str, List[Hit]] = {}
    for h in hits:
        by_reg.setdefault(h.base_reg, []).append(h)

    for reg, hs in by_reg.items():
        n = len(hs)
        for i, h in enumerate(hs):
            group = []
            j = i
            while j < n and hs[j].va - h.va <= window:
                group.append(hs[j])
                j += 1
            if len(group) < 2:
                continue
            fields = {x.field for x in group}
            disps = {x.disp for x in group}
            kinds = {x.kind for x in group}

            score = 0.0
            score += len(group) * 2.0
            score += len(fields) * 12.0
            if {"curve", "spin"}.issubset(fields):
                score += 35.0
            if {"curve_max", "spin_max"}.issubset(fields):
                score += 25.0
            if {"curve", "spin", "curve_max", "spin_max"}.issubset(fields):
                score += 80.0
            if any("store" in k or "fst" in k for k in kinds):
                score += 18.0
            if any(k.startswith("x87") for k in kinds):
                score += 8.0
            if any(k.startswith("sse") for k in kinds):
                score += 8.0
            if len(disps) >= 3:
                score += 20.0
            if len(disps) >= 4:
                score += 20.0

            # 너무 흔한 단순 mov-only보다 x87/sse float access 우선
            if all(k.startswith("mov_") for k in kinds):
                score -= 10.0

            lines = [f"0x{x.va:08X} {x.kind:15s} [{x.base_reg}+0x{x.disp:02X}] {x.field:10s} bytes={x.bytes_hex}" for x in group]
            clusters.append(Cluster(
                key_va=h.va,
                start_va=group[0].va,
                end_va=group[-1].va,
                score=score,
                base_reg=reg,
                hit_count=len(group),
                fields=",".join(sorted(fields)),
                kinds=",".join(sorted(kinds)),
                hit_lines=lines,
            ))

    # 같은 영역 중복 제거: start_va가 가까운 것은 높은 점수만 남김
    clusters.sort(key=lambda c: (-c.score, c.start_va))
    dedup: List[Cluster] = []
    for c in clusters:
        if any(abs(c.start_va - d.start_va) < 16 and c.base_reg == d.base_reg for d in dedup):
            continue
        dedup.append(c)
    return dedup


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--exe", default=r"C:\Pangya_US8JP\RELEASE SRV4\@Client EXE\ProjectG127.exe")
    ap.add_argument("--out-dir", default="logs\\spin_curve_static_candidates")
    ap.add_argument("--top", type=int, default=120)
    ap.add_argument("--window", type=int, default=96)
    args = ap.parse_args()

    exe = Path(args.exe)
    if not exe.exists():
        raise FileNotFoundError(str(exe))

    data = exe.read_bytes()
    image_base, sections = read_pe_sections(data)
    hits = find_patterns(data, image_base, sections)
    clusters = make_clusters(hits, args.window)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = out_dir / f"spin_curve_static_candidates_{stamp}.csv"
    txt_path = out_dir / f"spin_curve_static_candidates_{stamp}.txt"

    with csv_path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["rank", "score", "start_va", "end_va", "base_reg", "hit_count", "fields", "kinds", "detail"])
        for rank, c in enumerate(clusters[:args.top], 1):
            w.writerow([rank, f"{c.score:.1f}", f"0x{c.start_va:08X}", f"0x{c.end_va:08X}", c.base_reg, c.hit_count, c.fields, c.kinds, " | ".join(c.hit_lines)])

    with txt_path.open("w", encoding="utf-8") as f:
        f.write("========== Pangya Spin/Curve Static Access Candidates ==========\n")
        f.write(f"exe={exe}\n")
        f.write(f"image_base=0x{image_base:08X}\n")
        f.write(f"raw_hits={len(hits)} clusters={len(clusters)} window={args.window}\n")
        f.write(f"csv={csv_path}\n\n")
        for rank, c in enumerate(clusters[:args.top], 1):
            f.write(f"#{rank:03d} score={c.score:.1f} range=0x{c.start_va:08X}-0x{c.end_va:08X} base={c.base_reg} hits={c.hit_count} fields={c.fields} kinds={c.kinds}\n")
            for line in c.hit_lines[:20]:
                f.write("   " + line + "\n")
            f.write("\n")

    print("[INFO] exe=", exe)
    print(f"[INFO] image_base=0x{image_base:08X}")
    print(f"[INFO] raw_hits={len(hits)} clusters={len(clusters)}")
    print(f"[DONE] csv={csv_path}")
    print(f"[DONE] txt={txt_path}")
    print("[TOP]")
    for rank, c in enumerate(clusters[:20], 1):
        print(f"#{rank:03d} score={c.score:.1f} range=0x{c.start_va:08X}-0x{c.end_va:08X} base={c.base_reg} fields={c.fields} kinds={c.kinds}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
