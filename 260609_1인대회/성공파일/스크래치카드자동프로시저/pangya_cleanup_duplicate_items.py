# pangya_cleanup_duplicate_items.py
# UID 기준 My Room 중복 아이템 정리 도구
#
# 목적:
#   Memorial Coin batch 테스트 등으로 같은 착용 파츠/장비 typeid가 여러 row로 들어간 경우,
#   valid=1 중복 row를 찾아서 1개만 남기고 나머지를 valid=0 처리한다.
#
# 기본은 "삭제"가 아니라 "비활성화(valid=0)"라서 비교적 안전하다.
#
# 설치:
#   pip install pymysql
#
# 사용 예:
#   python .\pangya_cleanup_duplicate_items.py --uid 3 --scan
#   python .\pangya_cleanup_duplicate_items.py --uid 3 --prefix 8 --dry-run
#   python .\pangya_cleanup_duplicate_items.py --uid 3 --prefix 8 --apply
#   python .\pangya_cleanup_duplicate_items.py --uid 3 --typeid 0x08200013 --apply
#
# prefix 참고:
#   8  = Parts/의상 파츠 계열
#   16 = ClubSet 계열
#   24/26/27 = 수량형 아이템이 많으므로 중복 정리 비추천
#
# 주의:
#   - 최초에는 반드시 --scan 또는 --dry-run으로 확인.
#   - --apply 실행 전 자동으로 pangya_item_warehouse 백업 테이블을 만든다.
#   - 기본 keep 정책은 oldest, 즉 가장 오래된 item_id 1개를 남긴다.

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

import pymysql


STACKABLE_PREFIXES = {20, 24, 26, 27, 112, 124, 125}
DEFAULT_UNIQUE_PREFIXES = {4, 8, 16, 56, 57}


def parse_int(value: str | int | None):
    if value is None:
        return None
    if isinstance(value, int):
        return value
    value = str(value).strip()
    if value.lower().startswith("0x"):
        return int(value, 16)
    return int(value)


def connect(args):
    return pymysql.connect(
        host=args.host,
        user=args.user,
        password=args.password,
        database=args.db,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=True,
    )


def get_prefix(typeid: int) -> int:
    return (int(typeid) & 0xFF000000) >> 24


def backup_table(cur, uid: int, tag: str):
    table = f"bak_cleanup_dup_{tag}_item_warehouse_uid{uid}"
    cur.execute(f"DROP TABLE IF EXISTS `{table}`")
    cur.execute(f"CREATE TABLE `{table}` AS SELECT * FROM pangya_item_warehouse WHERE UID = %s", (uid,))
    return table


def find_duplicates(cur, uid: int, prefix: int | None = None, typeid: int | None = None, only_valid: bool = True):
    where = ["UID = %s"]
    params = [uid]

    if only_valid:
        where.append("valid = 1")

    if typeid is not None:
        where.append("typeid = %s")
        params.append(typeid)
    elif prefix is not None:
        where.append("((typeid & 0xFF000000) >> 24) = %s")
        params.append(prefix)
    else:
        # 기본 스캔은 비수량성으로 보는 prefix만
        placeholders = ",".join(["%s"] * len(DEFAULT_UNIQUE_PREFIXES))
        where.append(f"((typeid & 0xFF000000) >> 24) IN ({placeholders})")
        params.extend(sorted(DEFAULT_UNIQUE_PREFIXES))

    sql = f"""
        SELECT
            typeid,
            COUNT(*) AS cnt,
            MIN(item_id) AS min_item_id,
            MAX(item_id) AS max_item_id,
            GROUP_CONCAT(item_id ORDER BY item_id SEPARATOR ',') AS item_ids
        FROM pangya_item_warehouse
        WHERE {' AND '.join(where)}
        GROUP BY typeid
        HAVING COUNT(*) > 1
        ORDER BY cnt DESC, typeid
    """
    cur.execute(sql, params)
    return cur.fetchall()


def get_rows_for_typeid(cur, uid: int, typeid: int, only_valid: bool = True):
    where = "UID = %s AND typeid = %s"
    params = [uid, typeid]
    if only_valid:
        where += " AND valid = 1"
    cur.execute(
        f"""
        SELECT item_id, UID, typeid, valid, C0, C1, C2, C3, C4, regdate, Applytime, EndDate, flag, ItemType
        FROM pangya_item_warehouse
        WHERE {where}
        ORDER BY item_id
        """,
        params,
    )
    return cur.fetchall()


def choose_keep_item_id(rows, keep: str):
    if not rows:
        return None

    if keep == "oldest":
        return min(int(r["item_id"]) for r in rows)
    if keep == "newest":
        return max(int(r["item_id"]) for r in rows)

    raise ValueError(f"unknown keep: {keep}")


def print_duplicate_groups(cur, uid: int, groups, only_valid: bool = True, detail: bool = False):
    if not groups:
        print("[OK] 중복 group 없음")
        return

    print(f"[DUPLICATES] groups={len(groups)}")
    for g in groups:
        typeid = int(g["typeid"])
        prefix = get_prefix(typeid)
        print(
            f"  typeid=0x{typeid:08X} prefix={prefix} "
            f"cnt={g['cnt']} item_ids={g['item_ids']}"
        )

        if detail:
            rows = get_rows_for_typeid(cur, uid, typeid, only_valid=only_valid)
            for r in rows:
                print(
                    f"    item_id={r['item_id']} valid={r['valid']} "
                    f"C0={r['C0']} C1={r['C1']} C2={r['C2']} C3={r['C3']} C4={r['C4']} "
                    f"regdate={r['regdate']}"
                )


def cleanup_duplicates(cur, uid: int, groups, keep: str, mode: str, only_valid: bool = True):
    actions = []

    for g in groups:
        typeid = int(g["typeid"])
        rows = get_rows_for_typeid(cur, uid, typeid, only_valid=only_valid)

        if len(rows) <= 1:
            continue

        keep_id = choose_keep_item_id(rows, keep)
        remove_ids = [int(r["item_id"]) for r in rows if int(r["item_id"]) != keep_id]

        if not remove_ids:
            continue

        actions.append({
            "typeid": typeid,
            "hex_typeid": f"0x{typeid:08X}",
            "prefix": get_prefix(typeid),
            "keep_item_id": keep_id,
            "affected_item_ids": remove_ids,
            "mode": mode,
        })

        placeholders = ",".join(["%s"] * len(remove_ids))

        if mode == "invalidate":
            cur.execute(
                f"""
                UPDATE pangya_item_warehouse
                SET valid = 0
                WHERE UID = %s
                  AND item_id IN ({placeholders})
                """,
                (uid, *remove_ids),
            )
        elif mode == "delete":
            cur.execute(
                f"""
                DELETE FROM pangya_item_warehouse
                WHERE UID = %s
                  AND item_id IN ({placeholders})
                """,
                (uid, *remove_ids),
            )
        else:
            raise ValueError(f"unknown mode: {mode}")

    return actions


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--user", default="root")
    ap.add_argument("--password", default="root")
    ap.add_argument("--db", default="pangya-ssd")
    ap.add_argument("--uid", type=int, default=3)

    mode_group = ap.add_mutually_exclusive_group()
    mode_group.add_argument("--scan", action="store_true", help="중복 목록만 조회")
    mode_group.add_argument("--dry-run", action="store_true", help="정리 대상만 보여주고 변경하지 않음")
    mode_group.add_argument("--apply", action="store_true", help="실제로 중복 정리 실행")

    target_group = ap.add_mutually_exclusive_group()
    target_group.add_argument("--prefix", type=str, help="특정 prefix만 정리. 예: 8")
    target_group.add_argument("--typeid", type=str, help="특정 typeid만 정리. 예: 0x08200013")

    ap.add_argument("--keep", choices=["oldest", "newest"], default="oldest")
    ap.add_argument("--mode", choices=["invalidate", "delete"], default="invalidate")
    ap.add_argument("--include-invalid", action="store_true", help="valid=0까지 포함해 중복 판단")
    ap.add_argument("--detail", action="store_true")
    args = ap.parse_args()

    if not (args.scan or args.dry_run or args.apply):
        args.scan = True

    prefix = parse_int(args.prefix)
    typeid = parse_int(args.typeid)
    only_valid = not args.include_invalid

    if prefix in STACKABLE_PREFIXES and typeid is None:
        print(f"[WARN] prefix={prefix}는 수량형 아이템이 많아 일괄 중복 정리를 추천하지 않습니다.")
        print("       정말 필요하면 --typeid로 정확히 지정하세요.")
        return

    conn = connect(args)

    try:
        with conn.cursor() as cur:
            groups = find_duplicates(cur, args.uid, prefix=prefix, typeid=typeid, only_valid=only_valid)
            print_duplicate_groups(cur, args.uid, groups, only_valid=only_valid, detail=args.detail)

            if args.scan:
                return

            if not groups:
                return

            # dry-run actions preview
            preview = []
            for g in groups:
                rows = get_rows_for_typeid(cur, args.uid, int(g["typeid"]), only_valid=only_valid)
                keep_id = choose_keep_item_id(rows, args.keep)
                remove_ids = [int(r["item_id"]) for r in rows if int(r["item_id"]) != keep_id]
                preview.append({
                    "typeid": int(g["typeid"]),
                    "hex_typeid": f"0x{int(g['typeid']):08X}",
                    "prefix": get_prefix(int(g["typeid"])),
                    "keep_item_id": keep_id,
                    "affected_item_ids": remove_ids,
                    "mode": args.mode,
                })

            print("")
            print("[PREVIEW]")
            for a in preview:
                print(
                    f"  {a['hex_typeid']} keep={a['keep_item_id']} "
                    f"{args.mode}={a['affected_item_ids']}"
                )

            if args.dry_run:
                return

            if args.apply:
                confirm = input("\n실제로 정리할까요? YES 입력 시 실행: ").strip()
                if confirm != "YES":
                    print("취소했습니다.")
                    return

                tag = datetime.now().strftime("%Y%m%d_%H%M%S")
                backup_name = backup_table(cur, args.uid, tag)
                print(f"[BACKUP] {backup_name}")

                actions = cleanup_duplicates(cur, args.uid, groups, args.keep, args.mode, only_valid=only_valid)

                log_path = Path(f"cleanup_duplicate_items_uid{args.uid}_{tag}.json")
                log_path.write_text(json.dumps({
                    "uid": args.uid,
                    "backup_table": backup_name,
                    "keep": args.keep,
                    "mode": args.mode,
                    "only_valid": only_valid,
                    "actions": actions,
                }, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

                print(f"[DONE] actions={len(actions)}")
                print(f"[LOG] {log_path}")

    finally:
        conn.close()


if __name__ == "__main__":
    main()
