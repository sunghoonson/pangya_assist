# scratchy_batch_open_v3.py
# Scratchy Card 관리/일괄 오픈 스크립트 v3
#
# v3 추가:
#   실행하면 메뉴 표시
#     1. Scratchy Card 수량 채우기
#     2. Scratchy Card 일괄 오픈
#
# 기존 v2 기능:
#   - ProcGetScratchyCardTicket(uid)를 호출해 티켓 1장씩 차감
#   - scratchy_rate / scratchy_item 기준으로 보상 랜덤 선택
#   - USP_ADD_ITEM으로 보상 지급
#   - 레어면 ProcInsertScratchyRareWin 호출
#   - 결과 로그 json/csv/summary csv 저장
#
# 설치:
#   pip install pymysql
#
# 기본 실행:
#   python .\scratchy_batch_open_v3.py
#
# 바로 실행 옵션:
#   python .\scratchy_batch_open_v3.py --uid 3 --fill 7000
#   python .\scratchy_batch_open_v3.py --uid 3 --count 10
#   python .\scratchy_batch_open_v3.py --uid 3 --all

from __future__ import annotations

import argparse
import csv
import json
import random
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import pymysql


SCRATCHY_TICKET_TYPEIDS = (0x1A000030, 0x1A000033, 0x1A0000A3)


@dataclass
class Reward:
    name: str
    typeid: int
    numero: int
    quantidade: int
    probabilidade: int
    tipo: int
    flag: int
    active: int


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


def get_ticket_rows(cur, uid: int, include_zero: bool = False):
    placeholders = ",".join(["%s"] * len(SCRATCHY_TICKET_TYPEIDS))
    c0_cond = "" if include_zero else "AND C0 > 0"
    return fetchall(
        cur,
        f"""
        SELECT item_id, UID, typeid, C0, valid, flag, ItemType, regdate
        FROM pangya_item_warehouse
        WHERE UID = %s
          {c0_cond}
          AND typeid IN ({placeholders})
        ORDER BY typeid
        """,
        (uid, *SCRATCHY_TICKET_TYPEIDS),
    )


def get_ticket_count(cur, uid: int) -> int:
    rows = get_ticket_rows(cur, uid)
    return sum(int(r.get("C0") or 0) for r in rows)


def backup_tables(cur, uid: int, tag: str):
    backups = {
        f"bak_scratchy_{tag}_item_warehouse": f"SELECT * FROM pangya_item_warehouse WHERE UID = {uid}",
        f"bak_scratchy_{tag}_prob_sec": f"SELECT * FROM pangya_scratchy_prob_sec WHERE uid = {uid}",
        f"bak_scratchy_{tag}_rare_win": f"SELECT * FROM scratchy_rare_win WHERE UID = {uid}",
        f"bak_scratchy_{tag}_card": f"SELECT * FROM pangya_card WHERE UID = {uid}",
        f"bak_scratchy_{tag}_user_info": f"SELECT * FROM user_info WHERE UID = {uid}",
    }

    created = []
    for table, select_sql in backups.items():
        cur.execute(f"DROP TABLE IF EXISTS `{table}`")
        cur.execute(f"CREATE TABLE `{table}` AS {select_sql}")
        created.append(table)
    return created


def load_rates(cur):
    rows = fetchall(cur, "SELECT nome, tipo, probabilidade FROM scratchy_rate ORDER BY tipo")
    return [
        {
            "nome": r["nome"],
            "tipo": int(r["tipo"]),
            "probabilidade": int(r["probabilidade"]),
        }
        for r in rows
    ]


def load_rewards(cur):
    rows = fetchall(
        cur,
        """
        SELECT Name, TypeID, Numero, Quantidade, Probabilidade, Tipo, flag, Active
        FROM scratchy_item
        WHERE Active = 1
        ORDER BY Tipo, Probabilidade DESC, TypeID
        """,
    )

    return [
        Reward(
            name=str(r["Name"]),
            typeid=int(r["TypeID"]),
            numero=int(r["Numero"]),
            quantidade=int(r["Quantidade"]),
            probabilidade=int(r["Probabilidade"]),
            tipo=int(r["Tipo"]),
            flag=int(r["flag"]),
            active=int(r["Active"]),
        )
        for r in rows
    ]


def get_prob_sec(cur, uid: int) -> int:
    row = fetchone(cur, "SELECT scratchy_sec FROM pangya_scratchy_prob_sec WHERE uid = %s", (uid,))
    if not row:
        cur.execute("INSERT INTO pangya_scratchy_prob_sec(uid, scratchy_sec) VALUES(%s, 0)", (uid,))
        return 0
    return int(row["scratchy_sec"])


def set_prob_sec(cur, uid: int, value: int):
    cur.execute(
        """
        INSERT INTO pangya_scratchy_prob_sec(uid, scratchy_sec)
        VALUES(%s, %s)
        ON DUPLICATE KEY UPDATE scratchy_sec = VALUES(scratchy_sec)
        """,
        (uid, int(value)),
    )


def weighted_pick(items, weight_key):
    total = 0
    for x in items:
        total += max(0, int(x[weight_key] if isinstance(x, dict) else getattr(x, weight_key)))

    if total <= 0:
        raise RuntimeError("weight total <= 0")

    r = random.randint(1, total)
    acc = 0
    for x in items:
        w = max(0, int(x[weight_key] if isinstance(x, dict) else getattr(x, weight_key)))
        acc += w
        if r <= acc:
            return x
    return items[-1]


def choose_tipo(rates, prob_sec: int, prob_sec_mode: str):
    adjusted = []
    for r in rates:
        rr = dict(r)
        if prob_sec_mode == "add_rare" and rr["tipo"] == 1:
            rr["probabilidade"] += max(0, prob_sec)
        adjusted.append(rr)

    picked = weighted_pick(adjusted, "probabilidade")
    return int(picked["tipo"]), adjusted


def choose_reward(rewards: list[Reward], tipo: int):
    candidates = [r for r in rewards if r.tipo == tipo and r.active == 1]
    if not candidates:
        raise RuntimeError(f"No active scratchy_item rows for Tipo={tipo}")
    return weighted_pick(candidates, "probabilidade")


def call_proc_get_ticket_v2(cur, uid: int):
    before = get_ticket_count(cur, uid)

    cur.execute("CALL ProcGetScratchyCardTicket(%s)", (uid,))
    rows = []
    try:
        rows = cur.fetchall()
    except Exception:
        rows = []
    drain_result_sets(cur)

    after = get_ticket_count(cur, uid)
    consumed = before - after

    ticket_id = None
    if rows:
        ticket_id = rows[0].get("TICKET_ID")

    return {
        "ok": consumed == 1,
        "ticket_id": ticket_id,
        "before": before,
        "after": after,
        "consumed": consumed,
        "raw_rows": rows,
    }


def call_add_item(cur, uid: int, reward: Reward):
    cur.execute(
        "CALL USP_ADD_ITEM(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (
            uid,
            0,                  # GIFTFLAG
            0,                  # PURCHASE_IN
            0,                  # IDITEM
            reward.typeid,
            reward.flag,        # TYPEFLAG
            0,                  # TEMPO
            reward.quantidade,  # C_0
            0, 0, 0, 0,         # C_1 ~ C_4
            0.0, 0.0, 0.0, 0.0, # X,Y,Z,R
        ),
    )
    rows = cur.fetchall()
    drain_result_sets(cur)
    if rows:
        return rows[0].get("ITEM_ID")
    return None


def call_insert_rare_win(cur, uid: int, reward: Reward):
    cur.execute("CALL ProcInsertScratchyRareWin(%s, %s)", (uid, reward.typeid))
    try:
        cur.fetchall()
    except Exception:
        pass
    drain_result_sets(cur)


def summarize_rewards(results):
    c = Counter()
    qty = defaultdict(int)
    for r in results:
        key = (r["tipo"], r["typeid"], r["name"])
        c[key] += 1
        qty[key] += int(r["quantidade"])
    out = []
    for (tipo, typeid_, name), cnt in c.most_common():
        out.append({
            "tipo": tipo,
            "typeid": typeid_,
            "hex_typeid": f"0x{typeid_:08X}",
            "name": name,
            "hits": cnt,
            "total_quantity": qty[(tipo, typeid_, name)],
        })
    return out


def write_logs(prefix: str, results: list[dict[str, Any]], summary: list[dict[str, Any]], meta: dict[str, Any]):
    json_path = Path(prefix + ".json")
    csv_path = Path(prefix + ".csv")
    summary_path = Path(prefix + "_summary.csv")

    payload = {
        "meta": meta,
        "summary": summary,
        "results": results,
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    if results:
        with csv_path.open("w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=list(results[0].keys()))
            writer.writeheader()
            writer.writerows(results)

    if summary:
        with summary_path.open("w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=list(summary[0].keys()))
            writer.writeheader()
            writer.writerows(summary)

    return json_path, csv_path, summary_path


def show_ticket_rows(cur, uid: int):
    rows = get_ticket_rows(cur, uid, include_zero=True)
    print("")
    print("[현재 Scratchy Ticket]")
    if not rows:
        print("  없음")
        return
    for r in rows:
        print(
            f"  item_id={r['item_id']} typeid=0x{int(r['typeid']):08X} "
            f"C0={r['C0']} valid={r['valid']} flag={r['flag']}"
        )


def fill_tickets(args, amount: int):
    if amount <= 0:
        raise ValueError("수량은 1 이상이어야 합니다.")

    conn = connect(args)
    try:
        with conn.cursor() as cur:
            before_total = get_ticket_count(cur, args.uid)
            show_ticket_rows(cur, args.uid)

            rows = get_ticket_rows(cur, args.uid, include_zero=True)

            # 기존 row가 있으면 ORDER BY typeid 기준 첫 row에 추가.
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
                print(f"[OK] 기존 Scratchy Ticket row에 {amount}개 추가")
                print(f"     item_id={target['item_id']} typeid=0x{int(target['typeid']):08X}")
            else:
                # 기존 row가 없다면 Normal Scratchy Ticket(0x1A0000A3) 신규 지급.
                # USP_ADD_ITEM은 typeid prefix 0x1A -> passive item 케이스에서 pangya_item_warehouse에 추가한다.
                cur.execute(
                    "CALL USP_ADD_ITEM(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (
                        args.uid,
                        0,
                        0,
                        0,
                        0x1A0000A3,
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
                drain_result_sets(cur)
                print("")
                print(f"[OK] Scratchy Ticket row가 없어 신규로 {amount}개 지급")
                print("     typeid=0x1A0000A3")

            after_total = get_ticket_count(cur, args.uid)
            print("")
            print(f"[수량] {before_total} -> {after_total}")
            show_ticket_rows(cur, args.uid)

    finally:
        conn.close()


def open_scratchy(args, count_arg=None, all_arg=False):
    if args.seed is not None:
        random.seed(args.seed)

    now_tag = datetime.now().strftime("%Y%m%d_%H%M%S")
    conn = connect(args)

    results = []
    meta = {
        "uid": args.uid,
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "dry_run": args.dry_run,
        "prob_sec_mode": args.prob_sec_mode,
        "script": "scratchy_batch_open_v3.py",
    }

    try:
        with conn.cursor() as cur:
            ticket_before = get_ticket_count(cur, args.uid)
            meta["ticket_before"] = ticket_before

            if ticket_before <= 0:
                print("[ERROR] Scratchy ticket count is 0.")
                return

            count = ticket_before if all_arg else min(count_arg, ticket_before)
            meta["requested_count"] = count_arg if count_arg is not None else "all"
            meta["actual_count"] = count

            print(f"[INFO] UID={args.uid}")
            print(f"[INFO] tickets before={ticket_before}")
            print(f"[INFO] open count={count}")
            print(f"[INFO] dry_run={args.dry_run}")

            backup_tables_created = []
            if args.backup and not args.dry_run:
                backup_tables_created = backup_tables(cur, args.uid, now_tag)
                print("[INFO] backup tables:")
                for t in backup_tables_created:
                    print("  -", t)
            meta["backup_tables"] = backup_tables_created

            rates = load_rates(cur)
            rewards = load_rewards(cur)

            print("[INFO] rates:", rates)
            print("[INFO] active rewards:", len(rewards))

            virtual_prob_sec = get_prob_sec(cur, args.uid)

            for i in range(1, count + 1):
                prob_before = virtual_prob_sec if args.dry_run else get_prob_sec(cur, args.uid)

                tipo, _adjusted_rates = choose_tipo(rates, prob_before, args.prob_sec_mode)
                reward = choose_reward(rewards, tipo)

                ticket_info = {
                    "ok": True,
                    "ticket_id": None,
                    "before": None,
                    "after": None,
                    "consumed": 0,
                    "raw_rows": [],
                }
                item_id = None

                if not args.dry_run:
                    ticket_info = call_proc_get_ticket_v2(cur, args.uid)
                    if not ticket_info["ok"]:
                        print(
                            f"[STOP] ticket consume failed at iteration={i}, "
                            f"before={ticket_info['before']} after={ticket_info['after']} "
                            f"consumed={ticket_info['consumed']} rows={ticket_info['raw_rows']}"
                        )
                        break

                    item_id = call_add_item(cur, args.uid, reward)

                    if tipo == 1:
                        call_insert_rare_win(cur, args.uid, reward)
                        set_prob_sec(cur, args.uid, 0)
                    else:
                        set_prob_sec(cur, args.uid, prob_before + 1)

                    prob_after = get_prob_sec(cur, args.uid)
                else:
                    if tipo == 1:
                        virtual_prob_sec = 0
                    else:
                        virtual_prob_sec = prob_before + 1
                    prob_after = virtual_prob_sec

                row = {
                    "idx": i,
                    "ticket_id": ticket_info.get("ticket_id"),
                    "ticket_before": ticket_info.get("before"),
                    "ticket_after": ticket_info.get("after"),
                    "tipo": tipo,
                    "name": reward.name,
                    "typeid": reward.typeid,
                    "hex_typeid": f"0x{reward.typeid:08X}",
                    "quantidade": reward.quantidade,
                    "item_id": item_id,
                    "prob_sec_before": prob_before,
                    "prob_sec_after": prob_after,
                }
                results.append(row)

                if i <= 20 or i % 100 == 0 or i == count:
                    print(
                        f"[{i}/{count}] ticket {ticket_info.get('before')}->{ticket_info.get('after')} "
                        f"tipo={tipo} {reward.name} x{reward.quantidade} "
                        f"typeid=0x{reward.typeid:08X} item_id={item_id} "
                        f"prob_sec {prob_before}->{prob_after}"
                    )

            ticket_after = get_ticket_count(cur, args.uid)
            meta["ticket_after"] = ticket_after
            meta["processed_count"] = len(results)
            meta["finished_at"] = datetime.now().isoformat(timespec="seconds")

    finally:
        conn.close()

    summary = summarize_rewards(results)
    prefix = f"scratchy_batch_uid{args.uid}_{now_tag}"
    json_path, csv_path, summary_path = write_logs(prefix, results, summary, meta)

    print("")
    print("[DONE]")
    print(f"[PROCESSED] {len(results)}")
    print(f"[LOG] {json_path}")
    print(f"[LOG] {csv_path}")
    print(f"[LOG] {summary_path}")
    print("")
    print("[SUMMARY]")
    for s in summary[:30]:
        print(f"tipo={s['tipo']} typeid={s['hex_typeid']} {s['name']} hits={s['hits']} total_qntd={s['total_quantity']}")


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
    print(" Scratchy Card Tool v3")
    print("====================================")
    print(f"DB: {args.host} / {args.db}")
    print(f"UID 기본값: {args.uid}")
    print("")
    print("1. Scratchy Card 수량 채우기")
    print("2. Scratchy Card 일괄 오픈")
    print("0. 종료")
    print("")

    choice = input("선택: ").strip()

    if choice == "1":
        uid = ask_int(f"UID 입력 [{args.uid}]: ", args.uid)
        args.uid = uid

        conn = connect(args)
        try:
            with conn.cursor() as cur:
                show_ticket_rows(cur, args.uid)
        finally:
            conn.close()

        amount = ask_int("추가할 카드 수량 입력: ")
        confirm = input(f"UID {args.uid}에 Scratchy Card {amount}개를 추가할까요? (y/N): ").strip().lower()
        if confirm != "y":
            print("취소했습니다.")
            return
        fill_tickets(args, amount)

    elif choice == "2":
        uid = ask_int(f"UID 입력 [{args.uid}]: ", args.uid)
        args.uid = uid

        conn = connect(args)
        try:
            with conn.cursor() as cur:
                tickets = get_ticket_count(cur, args.uid)
                show_ticket_rows(cur, args.uid)
        finally:
            conn.close()

        print("")
        print("1. 전체 오픈")
        print("2. 수량 지정")
        sub = input("선택: ").strip()

        if sub == "1":
            confirm = input(f"현재 {tickets}장을 모두 오픈할까요? (y/N): ").strip().lower()
            if confirm != "y":
                print("취소했습니다.")
                return
            open_scratchy(args, all_arg=True)

        elif sub == "2":
            count = ask_int("오픈할 수량 입력: ")
            confirm = input(f"UID {args.uid}의 Scratchy Card {count}장을 오픈할까요? (y/N): ").strip().lower()
            if confirm != "y":
                print("취소했습니다.")
                return
            open_scratchy(args, count_arg=count, all_arg=False)

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
    mode.add_argument("--fill", type=int, help="Scratchy Card 수량을 지정한 만큼 추가")
    mode.add_argument("--count", type=int, help="지정 수량만큼 Scratchy Card 오픈")
    mode.add_argument("--all", action="store_true", help="남은 Scratchy Card 전부 오픈")

    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--prob-sec-mode", choices=["add_rare", "off"], default="add_rare")
    ap.add_argument("--backup", action="store_true", default=True)
    ap.add_argument("--no-backup", action="store_false", dest="backup")
    return ap.parse_args()


def main():
    args = parse_args()

    if args.fill is not None:
        fill_tickets(args, args.fill)
        return

    if args.count is not None:
        open_scratchy(args, count_arg=args.count, all_arg=False)
        return

    if args.all:
        open_scratchy(args, all_arg=True)
        return

    interactive_menu(args)


if __name__ == "__main__":
    main()
