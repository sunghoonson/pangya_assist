# pangya_memorial_schema_probe.py
# Memorial Coin / Memorial Shop 관련 DB 구조 탐색용
#
# 실행:
#   pip install pymysql
#   python .\pangya_memorial_schema_probe.py --uid 3
#
# 출력:
#   memorial_schema_probe_uid3_YYYYMMDD_HHMMSS.json

import argparse
import json
from pathlib import Path
from datetime import datetime

import pymysql


PREMIUM_MEMORIAL_COIN_TYPEID = 0x1A000272


def q(cur, sql, args=None):
    cur.execute(sql, args or ())
    return cur.fetchall()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--user", default="root")
    ap.add_argument("--password", default="root")
    ap.add_argument("--db", default="pangya-ssd")
    ap.add_argument("--uid", type=int, default=3)
    args = ap.parse_args()

    conn = pymysql.connect(
        host=args.host,
        user=args.user,
        password=args.password,
        database=args.db,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
    )

    out = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "uid": args.uid,
        "premium_memorial_coin_typeid": PREMIUM_MEMORIAL_COIN_TYPEID,
        "premium_memorial_coin_hex": f"0x{PREMIUM_MEMORIAL_COIN_TYPEID:08X}",
        "coin_rows": [],
        "tables_like_memorial_coin_gacha": {},
        "procedures_like_memorial_coin_gacha": [],
        "candidate_user_rows": {},
        "sample_tables": {},
    }

    try:
        with conn.cursor() as cur:
            out["coin_rows"] = q(cur, """
                SELECT item_id, UID, typeid, C0, valid, flag, ItemType, regdate
                FROM pangya_item_warehouse
                WHERE UID = %s
                  AND typeid = %s
                ORDER BY item_id
            """, (args.uid, PREMIUM_MEMORIAL_COIN_TYPEID))

            # 관련 테이블 찾기
            tables = q(cur, """
                SELECT TABLE_NAME
                FROM information_schema.TABLES
                WHERE TABLE_SCHEMA = %s
                  AND (
                       TABLE_NAME LIKE %s
                    OR TABLE_NAME LIKE %s
                    OR TABLE_NAME LIKE %s
                    OR TABLE_NAME LIKE %s
                    OR TABLE_NAME LIKE %s
                    OR TABLE_NAME LIKE %s
                  )
                ORDER BY TABLE_NAME
            """, (
                args.db,
                "%memorial%",
                "%coin%",
                "%gacha%",
                "%gatcha%",
                "%lottery%",
                "%rare%",
            ))

            for t in tables:
                name = t["TABLE_NAME"]
                cols = q(cur, """
                    SELECT COLUMN_NAME, COLUMN_TYPE, IS_NULLABLE, COLUMN_KEY, COLUMN_DEFAULT
                    FROM information_schema.COLUMNS
                    WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s
                    ORDER BY ORDINAL_POSITION
                """, (args.db, name))
                out["tables_like_memorial_coin_gacha"][name] = cols

                try:
                    out["sample_tables"][name] = q(cur, f"SELECT * FROM `{name}` LIMIT 100")
                except Exception as e:
                    out["sample_tables"][name] = [{"error": str(e)}]

            # 관련 프로시저 찾기
            out["procedures_like_memorial_coin_gacha"] = q(cur, """
                SELECT ROUTINE_NAME, ROUTINE_TYPE
                FROM information_schema.ROUTINES
                WHERE ROUTINE_SCHEMA = %s
                  AND (
                       ROUTINE_NAME LIKE %s
                    OR ROUTINE_NAME LIKE %s
                    OR ROUTINE_NAME LIKE %s
                    OR ROUTINE_NAME LIKE %s
                    OR ROUTINE_NAME LIKE %s
                  )
                ORDER BY ROUTINE_NAME
            """, (
                args.db,
                "%Memorial%",
                "%Coin%",
                "%Gacha%",
                "%Gatcha%",
                "%Lottery%",
            ))

            # UID 후보 테이블
            uid_cols = q(cur, """
                SELECT TABLE_NAME, COLUMN_NAME
                FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA = %s
                  AND COLUMN_NAME IN ('UID', 'uid', 'IDUSER', 'id_user', 'user_uid')
                ORDER BY TABLE_NAME, COLUMN_NAME
            """, (args.db,))

            for row in uid_cols:
                table = row["TABLE_NAME"]
                col = row["COLUMN_NAME"]
                if table in out["candidate_user_rows"]:
                    continue
                lower = table.lower()
                if not any(k in lower for k in ["memorial", "coin", "gacha", "rare", "shop", "item_warehouse"]):
                    continue
                try:
                    rows = q(cur, f"SELECT * FROM `{table}` WHERE `{col}` = %s LIMIT 50", (args.uid,))
                    if rows:
                        out["candidate_user_rows"][table] = {
                            "uid_column": col,
                            "rows": rows,
                        }
                except Exception:
                    pass

    finally:
        conn.close()

    path = Path(f"memorial_schema_probe_uid{args.uid}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"[DONE] wrote {path}")


if __name__ == "__main__":
    main()
