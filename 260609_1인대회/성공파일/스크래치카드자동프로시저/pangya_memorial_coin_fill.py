# pangya_memorial_coin_fill.py
# Premium Memorial Coin 수량 추가/조회용
#
# 실행:
#   pip install pymysql
#   python .\pangya_memorial_coin_fill.py --uid 3 --show
#   python .\pangya_memorial_coin_fill.py --uid 3 --fill 1000

import argparse
import pymysql

PREMIUM_MEMORIAL_COIN_TYPEID = 0x1A000272


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


def drain(cur):
    try:
        while cur.nextset():
            pass
    except Exception:
        pass


def show(cur, uid):
    cur.execute("""
        SELECT item_id, UID, typeid, C0, valid, flag, ItemType, regdate
        FROM pangya_item_warehouse
        WHERE UID = %s AND typeid = %s
        ORDER BY item_id
    """, (uid, PREMIUM_MEMORIAL_COIN_TYPEID))
    rows = cur.fetchall()
    print("[Premium Memorial Coin]")
    if not rows:
        print("  없음")
    for r in rows:
        print(f"  item_id={r['item_id']} typeid=0x{int(r['typeid']):08X} C0={r['C0']} valid={r['valid']} flag={r['flag']}")
    return rows


def fill(cur, uid, amount):
    if amount <= 0:
        raise ValueError("amount must be > 0")

    rows = show(cur, uid)
    before = sum(int(r["C0"] or 0) for r in rows)

    if rows:
        target = rows[0]
        cur.execute("""
            UPDATE pangya_item_warehouse
            SET C0 = C0 + %s,
                valid = 1
            WHERE UID = %s
              AND item_id = %s
        """, (amount, uid, target["item_id"]))
        print(f"[OK] 기존 row에 {amount}개 추가: item_id={target['item_id']}")
    else:
        cur.execute(
            "CALL USP_ADD_ITEM(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                uid,
                0,
                0,
                0,
                PREMIUM_MEMORIAL_COIN_TYPEID,
                0,
                0,
                amount,
                0, 0, 0, 0,
                0.0, 0.0, 0.0, 0.0,
            ),
        )
        try:
            cur.fetchall()
        except Exception:
            pass
        drain(cur)
        print(f"[OK] 신규 Premium Memorial Coin {amount}개 지급")

    rows_after = show(cur, uid)
    after = sum(int(r["C0"] or 0) for r in rows_after)
    print(f"[수량] {before} -> {after}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--user", default="root")
    ap.add_argument("--password", default="root")
    ap.add_argument("--db", default="pangya-ssd")
    ap.add_argument("--uid", type=int, default=3)
    ap.add_argument("--show", action="store_true")
    ap.add_argument("--fill", type=int)
    args = ap.parse_args()

    conn = connect(args)
    try:
        with conn.cursor() as cur:
            if args.fill is not None:
                fill(cur, args.uid, args.fill)
            else:
                show(cur, args.uid)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
