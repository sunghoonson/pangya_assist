# memorial_batch_open_v2_fast.py
# Premium Memorial Coin 빠른 일괄 사용/수량 채우기 도구
#
# v1 문제:
#   ProcGetMemorialRareItem 결과 전체를 보상 지급 대상으로 해석해서
#   후보 목록을 전부 지급할 가능성이 있었다.
#   또한 매 회차마다 프로시저/SELECT를 호출해 매우 느렸다.
#
# v2 방향:
#   - DB 테이블을 직접 읽어 확률표/후보표를 캐싱한다.
#   - 매 회차는 Python 메모리에서 랜덤 추첨만 한다.
#   - 실제 DB 반영은 마지막에 묶어서 처리한다.
#   - 코인은 USP_ADD_ITEM(..., C0=-N) 한 번으로 차감한다.
#
# 주의:
#   - 처음에는 반드시 --count 1 또는 --count 10으로 확인.
#   - v1을 이미 많이 돌렸다면 백업 테이블에서 복구 여부를 먼저 판단할 것.
#
# 설치:
#   pip install pymysql
#
# 실행:
#   python .\memorial_batch_open_v2_fast.py
#
# 바로 실행:
#   python .\memorial_batch_open_v2_fast.py --uid 3 --fill 1000
#   python .\memorial_batch_open_v2_fast.py --uid 3 --count 10
#   python .\memorial_batch_open_v2_fast.py --uid 3 --all
#   python .\memorial_batch_open_v2_fast.py --uid 3 --count 1000 --dry-run

from __future__ import annotations

import argparse
import csv
import json
import random
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

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


def fetchone(cur, sql, params=None):
    cur.execute(sql, params or ())
    return cur.fetchone()


def fetchall(cur, sql, params=None):
    cur.execute(sql, params or ())
    return cur.fetchall()


def drain_result_sets(cur):
    try:
        while cur.nextset():
            pass
    except Exception:
        pass


def get_coin_rows(cur, uid: int, include_zero: bool = False):
    c0_cond = "" if include_zero else "AND C0 > 0"
    return fetchall(
        cur,
        f"""
        SELECT item_id, UID, typeid, C0, valid, flag, ItemType, regdate
        FROM pangya_item_warehouse
        WHERE UID = %s
          {c0_cond}
          AND typeid = %s
        ORDER BY item_id
        """,
        (uid, PREMIUM_MEMORIAL_COIN_TYPEID),
    )


def get_coin_count(cur, uid: int) -> int:
    rows = get_coin_rows(cur, uid, include_zero=False)
    return sum(int(r.get("C0") or 0) for r in rows)


def show_coin_rows(cur, uid: int):
    rows = get_coin_rows(cur, uid, include_zero=True)
    print("")
    print("[현재 Premium Memorial Coin]")
    if not rows:
        print("  없음")
        return
    for r in rows:
        print(
            f"  item_id={r['item_id']} typeid=0x{int(r['typeid']):08X} "
            f"C0={r['C0']} valid={r['valid']} flag={r['flag']}"
        )


def call_usp_add_item(cur, uid: int, typeid: int, typeflag: int, tempo: int, c0: int, c1: int, c2: int, c3: int, c4: int):
    cur.execute(
        "CALL USP_ADD_ITEM(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (
            uid,
            0,                  # GIFTFLAG
            0,                  # PURCHASE_IN
            0,                  # IDITEM
            int(typeid),
            int(typeflag),
            int(tempo),
            int(c0),
            int(c1),
            int(c2),
            int(c3),
            int(c4),
            0.0, 0.0, 0.0, 0.0,
        ),
    )
    rows = cur.fetchall()
    drain_result_sets(cur)
    if rows:
        return rows[0].get("ITEM_ID")
    return None


def fill_coins(args, amount: int):
    if amount <= 0:
        raise ValueError("수량은 1 이상이어야 합니다.")

    conn = connect(args)
    try:
        with conn.cursor() as cur:
            before_total = get_coin_count(cur, args.uid)
            show_coin_rows(cur, args.uid)

            rows = get_coin_rows(cur, args.uid, include_zero=True)

            if rows:
                target = rows[0]
                cur.execute(
                    """
                    UPDATE pangya_item_warehouse
                    SET C0 = C0 + %s,
                        valid = 1
                    WHERE UID = %s
                      AND item_id = %s
                    """,
                    (amount, args.uid, target["item_id"]),
                )
                print("")
                print(f"[OK] 기존 Premium Memorial Coin row에 {amount}개 추가")
                print(f"     item_id={target['item_id']} typeid=0x{int(target['typeid']):08X}")
            else:
                call_usp_add_item(
                    cur,
                    uid=args.uid,
                    typeid=PREMIUM_MEMORIAL_COIN_TYPEID,
                    typeflag=0,
                    tempo=0,
                    c0=amount,
                    c1=0,
                    c2=0,
                    c3=0,
                    c4=0,
                )
                print("")
                print(f"[OK] Premium Memorial Coin row가 없어 신규로 {amount}개 지급")
                print("     typeid=0x1A000272")

            after_total = get_coin_count(cur, args.uid)
            print("")
            print(f"[수량] {before_total} -> {after_total}")
            show_coin_rows(cur, args.uid)

    finally:
        conn.close()


def backup_tables(cur, uid: int, tag: str):
    # 실제 존재하는 테이블만 백업
    candidates = {
        f"bak_memorial_fast_{tag}_item_warehouse": f"SELECT * FROM pangya_item_warehouse WHERE UID = {uid}",
        f"bak_memorial_fast_{tag}_card": f"SELECT * FROM pangya_card WHERE UID = {uid}",
        f"bak_memorial_fast_{tag}_character": f"SELECT * FROM pangya_character_information WHERE UID = {uid}",
        f"bak_memorial_fast_{tag}_caddie": f"SELECT * FROM pangya_caddie_information WHERE UID = {uid}",
        f"bak_memorial_fast_{tag}_mascot": f"SELECT * FROM pangya_mascot_info WHERE UID = {uid}",
        f"bak_memorial_fast_{tag}_rare_win": f"SELECT * FROM memorialshopitemrarewin WHERE UID = {uid}",
    }

    created = []
    for table, select_sql in candidates.items():
        try:
            cur.execute(f"DROP TABLE IF EXISTS `{table}`")
            cur.execute(f"CREATE TABLE `{table}` AS {select_sql}")
            created.append(table)
        except Exception as e:
            print(f"[WARN] backup skip {table}: {e}")
    return created


def weighted_pick(rows: list[dict[str, Any]], weight_key: str = "prob"):
    if not rows:
        raise RuntimeError("weighted_pick rows empty")

    total = 0
    for r in rows:
        total += max(0, int(r.get(weight_key) or 0))

    if total <= 0:
        return random.choice(rows)

    n = random.randint(1, total)
    acc = 0
    for r in rows:
        acc += max(0, int(r.get(weight_key) or 0))
        if n <= acc:
            return r
    return rows[-1]


def load_coin_tipo(cur, coin_typeid: int):
    row = fetchone(
        cur,
        "SELECT tipo FROM pangya_memorial_shop_coin_item WHERE typeid = %s",
        (coin_typeid,),
    )
    if not row:
        raise RuntimeError(f"coin type row not found: 0x{coin_typeid:08X}")
    return int(row["tipo"])


def load_rate_rows(cur, coin_typeid: int):
    # ProcGetMemorialShopRate와 동일한 SQL
    return fetchall(
        cur,
        """
        SELECT IF(b.tipo = 1 AND a.tipo = 1, a.probabilidade + 400, a.probabilidade) AS prob,
               a.tipo
        FROM pangya_memorial_shop_rate a,
             pangya_memorial_shop_coin_item b
        WHERE b.typeid = %s
        """,
        (coin_typeid,),
    )


def load_normal_rows(cur, coin_opt: int):
    # ProcGetMemorialRareItem TYPE=0과 동일한 로직
    tipo = 1 if coin_opt == 1 else 0
    return fetchall(
        cur,
        """
        SELECT probabilidade AS prob,
               typeid,
               qntd
        FROM pangya_memorial_shop_normal_item
        WHERE tipo = %s
        """,
        (tipo,),
    )


def load_rare_rows(cur, coin_opt: int):
    # Premium coin(@OPT=1)은 level 24 고정
    if coin_opt == 1:
        return fetchall(
            cur,
            """
            SELECT b.probabilidade AS prob,
                   b.typeid,
                   b.tipo,
                   b.flag
            FROM pangya_memorial_shop_level a,
                 pangya_memorial_shop_rare_item b
            WHERE a.`level` = 24
              AND b.gacha_num <= a.gacha_fim
            """,
        )

    # 일반 coin(@OPT=0)은 유저 레벨 기반이어야 하지만, fast script는 premium coin용.
    # 필요 시 확장.
    return fetchall(
        cur,
        """
        SELECT b.probabilidade AS prob,
               b.typeid,
               b.tipo,
               b.flag
        FROM pangya_memorial_shop_level a,
             pangya_memorial_shop_rare_item b
        WHERE a.`level` = 24
          AND b.gacha_num <= a.gacha_fim
        """,
    )


def get_columns(cur, table_name: str):
    rows = fetchall(
        cur,
        """
        SELECT COLUMN_NAME, DATA_TYPE
        FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = %s
        ORDER BY ORDINAL_POSITION
        """,
        (table_name,),
    )
    return rows


def load_luckyset_rows(cur):
    try:
        return fetchall(cur, "SELECT * FROM pangya_memorial_shop_luckyset")
    except Exception as e:
        print(f"[WARN] pangya_memorial_shop_luckyset load failed: {e}")
        return []


def infer_luckyset_map(lucky_rows: list[dict[str, Any]], rare_typeids: set[int]):
    """
    pangya_memorial_shop_luckyset 컬럼명을 모르는 상태에서도 최대한 자동 추정.
    - rare_typeid가 들어있는 컬럼을 owner_col로 추정
    - 같은 row의 다른 큰 정수 typeid를 component item typeid로 추정
    - c0~c4, flag, tempo 컬럼이 있으면 사용
    """
    if not lucky_rows:
        return {}, None, None

    cols = list(lucky_rows[0].keys())

    def as_int(v):
        try:
            return int(v)
        except Exception:
            return None

    # rare typeid와 매칭되는 컬럼 점수
    owner_scores = Counter()
    for row in lucky_rows:
        for col in cols:
            iv = as_int(row.get(col))
            if iv in rare_typeids:
                owner_scores[col] += 1

    if not owner_scores:
        return {}, None, None

    owner_col = owner_scores.most_common(1)[0][0]

    # component typeid 후보 컬럼
    component_scores = Counter()
    for row in lucky_rows:
        owner = as_int(row.get(owner_col))
        if owner not in rare_typeids:
            continue
        for col in cols:
            if col == owner_col:
                continue
            iv = as_int(row.get(col))
            if iv is None:
                continue
            # Pangya typeid는 대체로 0x04000000 이상이지만 0x00000001 같은 특수값도 있어
            # luckyset component는 로그상 0x08/0x24/0x70 계열이므로 큰 값 위주로 잡는다.
            if iv > 100000:
                component_scores[col] += 1

    if not component_scores:
        return {}, owner_col, None

    component_col = component_scores.most_common(1)[0][0]

    lower_cols = {c.lower(): c for c in cols}

    def get_col(row, names, default=0):
        for name in names:
            col = lower_cols.get(name.lower())
            if col is not None:
                return row.get(col, default)
        return default

    lucky_map = defaultdict(list)
    for row in lucky_rows:
        owner = as_int(row.get(owner_col))
        comp = as_int(row.get(component_col))
        if owner not in rare_typeids or comp is None:
            continue

        c0 = int(get_col(row, ["c0", "C0", "c_0", "C_0", "qntd", "quantidade"], 0) or 0)
        c1 = int(get_col(row, ["c1", "C1", "c_1", "C_1"], 0) or 0)
        c2 = int(get_col(row, ["c2", "C2", "c_2", "C_2"], 0) or 0)
        c3 = int(get_col(row, ["c3", "C3", "c_3", "C_3"], 0) or 0)
        c4 = int(get_col(row, ["c4", "C4", "c_4", "C_4"], 0) or 0)
        flag = int(get_col(row, ["flag", "Flag", "typeflag", "TYPEFLAG"], 0) or 0)
        tempo = int(get_col(row, ["tempo", "Tempo", "period", "Period"], 0) or 0)

        lucky_map[owner].append({
            "typeid": comp,
            "hex_typeid": f"0x{comp:08X}",
            "flag": flag,
            "tempo": tempo,
            "c0": c0,
            "c1": c1,
            "c2": c2,
            "c3": c3,
            "c4": c4,
            "source": "luckyset",
        })

    return dict(lucky_map), owner_col, component_col


def is_stackable_by_prefix(typeid: int):
    prefix = (int(typeid) & 0xFF000000) >> 24
    # USP_ADD_ITEM 기준:
    # 20 ball, 24 active item, 26/27 passive item, 112 aux part, 124/125 card류는 C0 수량성이 강함.
    return prefix in (20, 24, 26, 27, 112, 124, 125)


def aggregate_grants(item_events: list[dict[str, Any]]):
    """
    DB 호출 수를 줄이기 위한 묶기.
    - stackable 계열은 같은 typeid/flag/tempo/c1~c4끼리 C0 합산
    - 의상/파트/클럽셋 등 비수량 계열은 같은 typeid+c0~c4 조합을 1회만 호출
      실제 USP_ADD_ITEM도 기존 보유 중복은 수량 증가가 아니라 valid 처리에 가깝다.
    """
    grouped = {}

    for item in item_events:
        typeid = int(item["typeid"])
        prefix = (typeid & 0xFF000000) >> 24

        if is_stackable_by_prefix(typeid):
            key = ("stack", typeid, int(item.get("flag", 0)), int(item.get("tempo", 0)), int(item.get("c1", 0)), int(item.get("c2", 0)), int(item.get("c3", 0)), int(item.get("c4", 0)))
            if key not in grouped:
                grouped[key] = dict(item)
            else:
                grouped[key]["c0"] = int(grouped[key].get("c0", 0)) + int(item.get("c0", 0))
        else:
            key = ("once", typeid, int(item.get("flag", 0)), int(item.get("tempo", 0)), int(item.get("c0", 0)), int(item.get("c1", 0)), int(item.get("c2", 0)), int(item.get("c3", 0)), int(item.get("c4", 0)))
            if key not in grouped:
                grouped[key] = dict(item)
                grouped[key]["_duplicate_hits"] = 1
            else:
                grouped[key]["_duplicate_hits"] = int(grouped[key].get("_duplicate_hits", 1)) + 1

    return list(grouped.values())


def insert_rare_win_bulk(cur, uid: int, rare_typeids: list[int]):
    if not rare_typeids:
        return

    # 실제 테이블명은 SHOW TABLES 결과 기준 memorialshopitemrarewin.
    # 실패하면 프로시저 fallback.
    try:
        values = ",".join(["(%s,%s,NOW())"] * len(rare_typeids))
        params = []
        for typeid in rare_typeids:
            params.extend([uid, int(typeid)])
        cur.execute(f"INSERT INTO memorialshopitemrarewin(UID, TYPEID, REG_DATE) VALUES {values}", tuple(params))
        return
    except Exception as e:
        print(f"[WARN] bulk rare win insert failed, fallback to procedure: {e}")

    for typeid in rare_typeids:
        cur.execute("CALL ProcInsertMemorialShopItemRareWin(%s, %s)", (uid, int(typeid)))
        try:
            cur.fetchall()
        except Exception:
            pass
        drain_result_sets(cur)


def consume_coins_once(cur, uid: int, count: int):
    if count <= 0:
        return None
    return call_usp_add_item(
        cur,
        uid=uid,
        typeid=PREMIUM_MEMORIAL_COIN_TYPEID,
        typeflag=0,
        tempo=0,
        c0=-int(count),
        c1=0,
        c2=0,
        c3=0,
        c4=0,
    )


def simulate_memorial(cur, uid: int, count: int):
    coin_typeid = PREMIUM_MEMORIAL_COIN_TYPEID
    coin_opt = load_coin_tipo(cur, coin_typeid)
    rate_rows = load_rate_rows(cur, coin_typeid)
    normal_rows = load_normal_rows(cur, coin_opt)
    rare_rows = load_rare_rows(cur, coin_opt)

    rare_typeids = {int(r["typeid"]) for r in rare_rows}
    lucky_rows = load_luckyset_rows(cur)
    lucky_map, owner_col, component_col = infer_luckyset_map(lucky_rows, rare_typeids)

    print(f"[INFO] coin opt/tipo={coin_opt}")
    print(f"[INFO] rate rows={len(rate_rows)} normal rows={len(normal_rows)} rare rows={len(rare_rows)}")
    print(f"[INFO] luckyset rows={len(lucky_rows)} owner_col={owner_col} component_col={component_col} mapped rare sets={len(lucky_map)}")

    if not rate_rows:
        raise RuntimeError("rate rows empty")
    if not normal_rows:
        raise RuntimeError("normal rows empty")
    if not rare_rows:
        raise RuntimeError("rare rows empty")

    results = []
    item_events = []
    rare_win_typeids = []

    for i in range(1, count + 1):
        rate = weighted_pick(rate_rows, "prob")
        rate_tipo = int(rate["tipo"])

        if rate_tipo == 0:
            normal = weighted_pick(normal_rows, "prob")
            typeid = int(normal["typeid"])
            qntd = int(normal.get("qntd") or 1)
            item = {
                "typeid": typeid,
                "hex_typeid": f"0x{typeid:08X}",
                "flag": 0,
                "tempo": 0,
                "c0": qntd,
                "c1": 0,
                "c2": 0,
                "c3": 0,
                "c4": 0,
                "source": "normal",
            }
            item_events.append(item)
            result_items = [item]
            rare_typeid = 0

        else:
            rare = weighted_pick(rare_rows, "prob")
            rare_typeid = int(rare["typeid"])
            rare_win_typeids.append(rare_typeid)

            if rare_typeid in lucky_map:
                result_items = [dict(x) for x in lucky_map[rare_typeid]]
            else:
                # luckyset이 없는 rare는 rare typeid 자체를 지급.
                # GameServer도 flag를 이용해 typeid 자체를 지급하는 경우가 있을 수 있다.
                result_items = [{
                    "typeid": rare_typeid,
                    "hex_typeid": f"0x{rare_typeid:08X}",
                    "flag": int(rare.get("flag") or 0),
                    "tempo": 0,
                    "c0": 1,
                    "c1": 0,
                    "c2": 0,
                    "c3": 0,
                    "c4": 0,
                    "source": "rare_direct",
                }]

            item_events.extend(result_items)

        results.append({
            "idx": i,
            "rate_tipo": rate_tipo,
            "rare_typeid": rare_typeid,
            "hex_rare_typeid": f"0x{rare_typeid:08X}" if rare_typeid else "",
            "items": result_items,
        })

    return {
        "coin_opt": coin_opt,
        "rate_rows": rate_rows,
        "normal_rows_count": len(normal_rows),
        "rare_rows_count": len(rare_rows),
        "lucky_rows_count": len(lucky_rows),
        "lucky_owner_col": owner_col,
        "lucky_component_col": component_col,
        "results": results,
        "item_events": item_events,
        "rare_win_typeids": rare_win_typeids,
    }


def summarize_results(results: list[dict[str, Any]]):
    item_counter = Counter()
    rare_counter = Counter()

    for row in results:
        if row.get("rare_typeid"):
            rare_counter[(row["rare_typeid"], row["hex_rare_typeid"])] += 1
        for item in row.get("items", []):
            key = (
                int(item["typeid"]),
                item["hex_typeid"],
                item.get("source", ""),
                int(item.get("c0", 0)),
                int(item.get("c1", 0)),
                int(item.get("c2", 0)),
                int(item.get("c3", 0)),
                int(item.get("c4", 0)),
            )
            item_counter[key] += 1

    item_summary = []
    for (typeid, hex_typeid, source, c0, c1, c2, c3, c4), hits in item_counter.most_common():
        item_summary.append({
            "typeid": typeid,
            "hex_typeid": hex_typeid,
            "source": source,
            "hits": hits,
            "c0": c0,
            "c1": c1,
            "c2": c2,
            "c3": c3,
            "c4": c4,
        })

    rare_summary = []
    for (typeid, hex_typeid), hits in rare_counter.most_common():
        rare_summary.append({
            "rare_typeid": typeid,
            "hex_rare_typeid": hex_typeid,
            "hits": hits,
        })

    return item_summary, rare_summary


def write_logs(prefix: str, meta: dict[str, Any], results: list[dict[str, Any]], item_summary: list[dict[str, Any]], rare_summary: list[dict[str, Any]], grants: list[dict[str, Any]]):
    json_path = Path(prefix + ".json")
    item_summary_path = Path(prefix + "_item_summary.csv")
    rare_summary_path = Path(prefix + "_rare_summary.csv")
    grants_path = Path(prefix + "_grants.csv")

    json_path.write_text(
        json.dumps(
            {
                "meta": meta,
                "item_summary": item_summary,
                "rare_summary": rare_summary,
                "grants": grants,
                "results": results,
            },
            ensure_ascii=False,
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )

    if item_summary:
        with item_summary_path.open("w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=list(item_summary[0].keys()))
            writer.writeheader()
            writer.writerows(item_summary)

    if rare_summary:
        with rare_summary_path.open("w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=list(rare_summary[0].keys()))
            writer.writeheader()
            writer.writerows(rare_summary)

    if grants:
        keys = ["typeid", "hex_typeid", "source", "flag", "tempo", "c0", "c1", "c2", "c3", "c4", "_duplicate_hits", "item_id"]
        with grants_path.open("w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(grants)

    return json_path, item_summary_path, rare_summary_path, grants_path


def open_memorial_fast(args, count_arg=None, all_arg=False):
    if args.seed is not None:
        random.seed(args.seed)

    now_tag = datetime.now().strftime("%Y%m%d_%H%M%S")
    conn = connect(args)

    meta = {
        "uid": args.uid,
        "script": "memorial_batch_open_v2_fast.py",
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "dry_run": args.dry_run,
    }

    try:
        with conn.cursor() as cur:
            coin_before = get_coin_count(cur, args.uid)
            meta["coin_before"] = coin_before

            if coin_before <= 0:
                print("[ERROR] Premium Memorial Coin count is 0.")
                return

            count = coin_before if all_arg else min(int(count_arg), coin_before)
            meta["requested_count"] = count_arg if count_arg is not None else "all"
            meta["actual_count"] = count

            print(f"[INFO] UID={args.uid}")
            print(f"[INFO] Premium Memorial Coin before={coin_before}")
            print(f"[INFO] open count={count}")
            print(f"[INFO] dry_run={args.dry_run}")

            backup_tables_created = []
            if args.backup and not args.dry_run:
                backup_tables_created = backup_tables(cur, args.uid, now_tag)
                print("[INFO] backup tables:")
                for t in backup_tables_created:
                    print("  -", t)
            meta["backup_tables"] = backup_tables_created

            sim = simulate_memorial(cur, args.uid, count)
            results = sim["results"]
            item_events = sim["item_events"]
            rare_win_typeids = sim["rare_win_typeids"]

            item_summary, rare_summary = summarize_results(results)
            grants = aggregate_grants(item_events)

            meta.update({
                "coin_opt": sim["coin_opt"],
                "normal_rows_count": sim["normal_rows_count"],
                "rare_rows_count": sim["rare_rows_count"],
                "lucky_rows_count": sim["lucky_rows_count"],
                "lucky_owner_col": sim["lucky_owner_col"],
                "lucky_component_col": sim["lucky_component_col"],
                "event_item_count": len(item_events),
                "grouped_grant_count": len(grants),
                "rare_win_count": len(rare_win_typeids),
            })

            print(f"[INFO] simulated results={len(results)} item_events={len(item_events)} grouped_grants={len(grants)} rare_wins={len(rare_win_typeids)}")

            if not args.dry_run:
                print("[INFO] applying rare win logs...")
                insert_rare_win_bulk(cur, args.uid, rare_win_typeids)

                print("[INFO] applying grouped item grants...")
                for idx, g in enumerate(grants, 1):
                    item_id = call_usp_add_item(
                        cur,
                        uid=args.uid,
                        typeid=g["typeid"],
                        typeflag=int(g.get("flag", 0)),
                        tempo=int(g.get("tempo", 0)),
                        c0=int(g.get("c0", 0)),
                        c1=int(g.get("c1", 0)),
                        c2=int(g.get("c2", 0)),
                        c3=int(g.get("c3", 0)),
                        c4=int(g.get("c4", 0)),
                    )
                    g["item_id"] = item_id
                    if idx <= 20 or idx % 100 == 0 or idx == len(grants):
                        print(f"  [{idx}/{len(grants)}] grant 0x{int(g['typeid']):08X} C0={g.get('c0')} C1={g.get('c1')} C2={g.get('c2')} C3={g.get('c3')} C4={g.get('c4')}")

                print("[INFO] consuming coins once...")
                consume_coins_once(cur, args.uid, count)

            coin_after = get_coin_count(cur, args.uid)
            meta["coin_after"] = coin_after
            meta["processed_count"] = len(results)
            meta["finished_at"] = datetime.now().isoformat(timespec="seconds")

    finally:
        conn.close()

    prefix = f"memorial_fast_uid{args.uid}_{now_tag}"
    json_path, item_summary_path, rare_summary_path, grants_path = write_logs(prefix, meta, results, item_summary, rare_summary, grants)

    print("")
    print("[DONE]")
    print(f"[PROCESSED] {len(results)}")
    print(f"[LOG] {json_path}")
    print(f"[LOG] {item_summary_path}")
    print(f"[LOG] {rare_summary_path}")
    print(f"[LOG] {grants_path}")
    print("")
    print("[SUMMARY TOP 20]")
    for s in item_summary[:20]:
        print(
            f"typeid={s['hex_typeid']} source={s['source']} hits={s['hits']} "
            f"C0={s['c0']} C1={s['c1']} C2={s['c2']} C3={s['c3']} C4={s['c4']}"
        )


def ask_int(prompt: str, default: int | None = None) -> int:
    while True:
        raw = input(prompt).strip()
        if raw == "" and default is not None:
            return default
        try:
            return int(raw)
        except ValueError:
            print("숫자로 입력하세요.")


def interactive_menu(args):
    print("")
    print("====================================")
    print(" Premium Memorial Coin Tool v2 Fast")
    print("====================================")
    print(f"DB: {args.host} / {args.db}")
    print(f"UID 기본값: {args.uid}")
    print("")
    print("1. Premium Memorial Coin 수량 채우기")
    print("2. Premium Memorial Coin 빠른 일괄 사용")
    print("3. Premium Memorial Coin 빠른 일괄 사용 dry-run")
    print("0. 종료")
    print("")

    choice = input("선택: ").strip()

    if choice == "1":
        uid = ask_int(f"UID 입력 [{args.uid}]: ", args.uid)
        args.uid = uid
        conn = connect(args)
        try:
            with conn.cursor() as cur:
                show_coin_rows(cur, args.uid)
        finally:
            conn.close()

        amount = ask_int("추가할 코인 수량 입력: ")
        confirm = input(f"UID {args.uid}에 Premium Memorial Coin {amount}개를 추가할까요? (y/N): ").strip().lower()
        if confirm != "y":
            print("취소했습니다.")
            return
        fill_coins(args, amount)

    elif choice in ("2", "3"):
        uid = ask_int(f"UID 입력 [{args.uid}]: ", args.uid)
        args.uid = uid
        args.dry_run = choice == "3"

        conn = connect(args)
        try:
            with conn.cursor() as cur:
                coins = get_coin_count(cur, args.uid)
                show_coin_rows(cur, args.uid)
        finally:
            conn.close()

        print("")
        print("1. 전체 사용")
        print("2. 수량 지정")
        sub = input("선택: ").strip()

        if sub == "1":
            confirm = input(f"현재 {coins}개를 모두 사용할까요? (y/N): ").strip().lower()
            if confirm != "y":
                print("취소했습니다.")
                return
            open_memorial_fast(args, all_arg=True)

        elif sub == "2":
            count = ask_int("사용할 수량 입력: ")
            confirm = input(f"UID {args.uid}의 Premium Memorial Coin {count}개를 사용할까요? (y/N): ").strip().lower()
            if confirm != "y":
                print("취소했습니다.")
                return
            open_memorial_fast(args, count_arg=count, all_arg=False)

        else:
            print("잘못된 선택입니다.")

    elif choice == "0":
        print("종료합니다.")
    else:
        print("잘못된 선택입니다.")


def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--user", default="root")
    ap.add_argument("--password", default="root")
    ap.add_argument("--db", default="pangya-ssd")
    ap.add_argument("--uid", type=int, default=3)

    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--fill", type=int)
    mode.add_argument("--count", type=int)
    mode.add_argument("--all", action="store_true")

    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--backup", action="store_true", default=True)
    ap.add_argument("--no-backup", action="store_false", dest="backup")
    return ap.parse_args()


def main():
    args = parse_args()

    if args.fill is not None:
        fill_coins(args, args.fill)
        return

    if args.count is not None:
        open_memorial_fast(args, count_arg=args.count, all_arg=False)
        return

    if args.all:
        open_memorial_fast(args, all_arg=True)
        return

    interactive_menu(args)


if __name__ == "__main__":
    main()
