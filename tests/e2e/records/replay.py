"""Reproduce RPCN's save writes against the real save-admin and be, and judge what be recorded.

A game save is two steps: a new .tdt under a new data_id, then the tus_data row pointing at it.
Phases run in order, each a separate process, so the runner can stop services between them.
"""

import json
import os
import sqlite3
import sys
import time
from datetime import date, datetime, timedelta, timezone

import psycopg

import tdt_admin as ta

ROOT = "/home/ec2-user/rpcn-data"
DB_PATH = f"{ROOT}/db/rpcn.db"
TUS_DIR = f"{ROOT}/tus_data"
STATE_PATH = f"{ROOT}/replay-state.json"
TICK_EPOCH = 62135596800
BULK_PLAYERS = 450
NAMES = "alice bob carol dave erin frank grace henry ivan judy kim leo mia nick olga pete quinn rosa sam tina".split()
PG = "host=postgres dbname=tag2now user=tag2now password=tag2now"
START = datetime(2026, 11, 2, 3, 0, tzinfo=timezone.utc)
PAUL, LAW, LEI, KING, YOSHI, NINA, JIN = 0, 1, 2, 3, 4, 5, 9


def at(hour, minute=0, second=0):
    return START + timedelta(hours=hour, minutes=minute, seconds=second)


# ---- RPCN's side ---------------------------------------------------------------


def rpcn():
    return sqlite3.connect(DB_PATH, timeout=10)


def next_data_id():
    con = rpcn()
    top = con.execute("SELECT max(data_id) FROM tus_data").fetchone()[0]
    con.close()
    return (top or 1000) + 1


def build_save(player, own=()):
    b = bytearray(ta.REC)
    for char_id, (wins, losses) in player["chars"].items():
        o = ta.CHAR_BASE + int(char_id) * ta.CHAR_STRIDE
        b[o + ta.SLOT_RANK] = player.get("ranks", {}).get(char_id, 12)
        b[o + ta.SLOT_WIN : o + ta.SLOT_WIN + 4] = wins.to_bytes(4, "big")
        b[o + ta.SLOT_LOSS : o + ta.SLOT_LOSS + 4] = losses.to_bytes(4, "big")
    total = player["wins"] + player["losses"]
    b[ta.OFF_TOTAL : ta.OFF_TOTAL + 4] = total.to_bytes(4, "big")
    b[ta.OFF_WINS : ta.OFF_WINS + 4] = player["wins"].to_bytes(4, "big")
    b[ta.OFF_LOSSES : ta.OFF_LOSSES + 4] = player["losses"].to_bytes(4, "big")
    if own:
        b[ta.OFF_MATCH_PENDING] = 1
        b[ta.OFF_OWN_CHAR_1], b[ta.OFF_OWN_CHAR_2] = own[0], own[-1]
    ta.reseal(b)
    return b


def write_file(data_id, content):
    with open(f"{TUS_DIR}/{data_id:020d}.tdt", "wb") as f:
        f.write(bytes(content))


def point_row(npid, data_id, moment):
    tick = (int(moment.timestamp()) + TICK_EPOCH) * 1_000_000
    con = rpcn()
    with con:
        uid = con.execute("SELECT user_id FROM account WHERE username = ?", (npid,)).fetchone()[0]
        con.execute(
            "INSERT INTO tus_data (owner_id, communication_id, slot_id, data_id, data_info, timestamp, author_id) "
            "VALUES (?, ?, ?, ?, x'', ?, ?) ON CONFLICT (owner_id, communication_id, slot_id) "
            "DO UPDATE SET data_id = excluded.data_id, timestamp = excluded.timestamp",
            (uid, ta.COM_ID.encode(), ta.SLOT, data_id, tick, uid),
        )
    con.close()


def game_save(player, moment, own=(), wait=True, data_id=None):
    data_id = data_id or next_data_id()
    write_file(data_id, build_save(player, own))
    point_row(player["npid"], data_id, moment)
    if wait:
        wait_for_state(player["npid"], data_id)
    return data_id


def record(player, won, chars):
    player["wins" if won else "losses"] += 1
    for char_id in chars:
        wins, losses = player["chars"].get(str(char_id), [0, 0])
        player["chars"][str(char_id)] = [wins + won, losses + (not won)]


def play(player, won, chars, moment, own=(), wait=True):
    """The result save: the record rises and nothing is pending."""
    record(player, won, chars)
    return game_save(player, moment, own=own, wait=wait)


# ---- be's side -----------------------------------------------------------------


def pg():
    return psycopg.connect(PG, autocommit=True)


def rows(sql, *params):
    with pg() as con:
        return con.execute(sql, params).fetchall()


def wait_until(check, what, seconds=30):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if check():
            return
        time.sleep(0.1)
    raise TimeoutError(f"timed out waiting for {what}")


def wait_for_state(npid, data_id):
    wait_until(
        lambda: rows("SELECT 1 FROM save_states WHERE npid = %s AND data_id >= %s", npid, data_id),
        f"{npid} to reach data_id {data_id}",
    )


def wait_for_queue():
    wait_until(lambda: not rows("SELECT 1 FROM match_events WHERE status = 'pending' LIMIT 1"), "the queue to drain")


def open_room(room_id, first, second, opened, last_seen):
    """What the collector writes for a two-member rank room."""
    with pg() as con:
        con.execute(
            "INSERT INTO rank_match_snapshots (room_id, created_dt, last_seen_at, match_date, rank_id, "
            "user1_npid, user1_online_name, user2_npid, user2_online_name) "
            "VALUES (%s, %s, %s, %s, 10, %s, %s, %s, %s)",
            (room_id, opened, last_seen, date(2026, 11, 2), first, first, second, second),
        )


def ranks_of(npid):
    """The ranks of each match the player's own save showed, oldest first."""
    return [
        row[0]
        for row in rows(
            "SELECT e.ranks FROM matches m JOIN match_events e ON e.id IN (m.p1_event_id, m.p2_event_id) "
            "WHERE e.npid = %s ORDER BY m.played_at",
            npid,
        )
    ]


def matches(*npids):
    """Each match the players were in, oldest first: (1P, 2P, winning side, 1P's characters, 2P's characters).
    A side's characters are None when its save was not seen."""
    return rows(
        "SELECT m.p1_npid, m.p2_npid, m.winner, e1.chars, e2.chars FROM matches m "
        "LEFT JOIN match_events e1 ON e1.id = m.p1_event_id LEFT JOIN match_events e2 ON e2.id = m.p2_event_id "
        "WHERE m.p1_npid = ANY(%s) OR m.p2_npid = ANY(%s) ORDER BY m.played_at, m.id",
        list(npids),
        list(npids),
    )


# ---- scenarios -----------------------------------------------------------------


class Report:
    def __init__(self):
        self.lines = []

    def check(self, number, name, got, want):
        passed = got == want
        self.lines.append((number, name, passed))
        print(f"[{'PASS' if passed else 'FAIL'}] {number:>2} {name}")
        if not passed:
            print(f"       got  {got}\n       want {want}")


def seeded(npid):
    """A player as the seed saved them: Paul only, at the default rank."""
    return {"npid": npid, "wins": 10, "losses": 10, "chars": {str(PAUL): [10, 10]}}


def seed(state):
    os.makedirs(f"{ROOT}/db", exist_ok=True)
    os.makedirs(TUS_DIR, exist_ok=True)
    con = rpcn()
    con.executescript(
        "CREATE TABLE account ( user_id INTEGER PRIMARY KEY, username TEXT NOT NULL );"
        "CREATE TABLE tus_data ( owner_id UNSIGNED BIGINT NOT NULL, communication_id TEXT NOT NULL, "
        "slot_id INTEGER NOT NULL, data_id UNSIGNED BIGINT NOT NULL, data_info BLOB NOT NULL, "
        "timestamp UNSIGNED BIGINT NOT NULL, author_id UNSIGNED BIGINT NOT NULL, "
        "PRIMARY KEY (owner_id, communication_id, slot_id) );"
    )
    names = NAMES + [f"bulk{i}" for i in range(BULK_PLAYERS)]
    with con:
        con.executemany("INSERT INTO account (user_id, username) VALUES (?, ?)", list(enumerate(names, 1)))
    con.close()
    for npid in names:
        player = seeded(npid)
        game_save(player, at(0), wait=False)
        if npid in NAMES:
            state[npid] = player
    print(f"seeded {len(names)} accounts")


def scenarios(state, report):
    players = len(NAMES) + BULK_PLAYERS
    wait_until(lambda: rows("SELECT count(*) FROM save_states")[0][0] == players, "the baseline", seconds=60)
    report.check(1, "baseline of everyone, no events", rows("SELECT count(*) FROM match_events")[0][0], 0)

    alice, bob = state["alice"], state["bob"]
    open_room(101, "alice", "bob", at(1), at(1, 4))
    game_save(alice, at(1, 0, 5), own=(JIN, PAUL))
    game_save(bob, at(1, 0, 6), own=(NINA, LAW))
    play(alice, True, (JIN, PAUL), at(1, 3, 10))
    play(bob, False, (NINA, LAW), at(1, 3, 14))
    wait_for_queue()
    report.check(
        2,
        "tag match joined, tag order kept",
        matches("alice", "bob"),
        [("alice", "bob", 1, [JIN, PAUL], [NINA, LAW])],
    )

    carol, dave = state["carol"], state["dave"]
    open_room(103, "carol", "dave", at(2), at(2, 4))
    game_save(carol, at(2, 0, 5), own=(KING, KING))
    game_save(dave, at(2, 0, 6), own=(YOSHI, YOSHI))
    play(carol, False, (KING,), at(2, 3, 1))
    play(dave, True, (YOSHI,), at(2, 3, 2))
    wait_for_queue()
    report.check(
        3,
        "solo entry",
        matches("carol", "dave"),
        [("carol", "dave", 2, [KING], [YOSHI])],
    )

    erin, frank = state["erin"], state["frank"]
    open_room(104, "erin", "frank", at(3), at(3, 12))
    want = []
    for game, erin_won in enumerate((True, False, True)):
        begin = 3 * game
        game_save(erin, at(3, begin, 5), own=(PAUL, LAW))
        game_save(frank, at(3, begin, 6), own=(LEI, KING))
        play(erin, erin_won, (PAUL, LAW), at(3, begin + 2, 50))
        play(frank, not erin_won, (LEI, KING), at(3, begin + 2, 53))
        want += [("erin", "frank", 1 if erin_won else 2, [PAUL, LAW], [LEI, KING])]
    wait_for_queue()
    report.check(4, "three matches in one reused room", matches("erin", "frank"), want)

    grace, henry = state["grace"], state["henry"]
    open_room(105, "grace", "henry", at(4), at(4, 8))
    game_save(grace, at(4, 0, 5), own=(JIN, LEI))
    game_save(henry, at(4, 0, 6), own=(LAW, NINA))
    # The result save was replaced before anyone read it: only the rematch's start save shows.
    play(grace, True, (JIN, LEI), at(4, 3, 10), own=(KING, YOSHI))
    play(henry, False, (LAW, NINA), at(4, 3, 12), own=(PAUL, LEI))
    play(grace, False, (KING, YOSHI), at(4, 6, 10))
    play(henry, True, (PAUL, LEI), at(4, 6, 12))
    wait_for_queue()
    report.check(
        5,
        "a result carried on the rematch's start save",
        matches("grace", "henry"),
        [("grace", "henry", 1, [JIN, LEI], [LAW, NINA]), ("grace", "henry", 2, [KING, YOSHI], [PAUL, LEI])],
    )

    ivan = state["ivan"]
    game_save(ivan, at(5))
    report.check(6, "a re-upload is no match", rows("SELECT count(*) FROM match_events WHERE npid = 'ivan'")[0][0], 0)

    judy, kim = state["judy"], state["kim"]
    open_room(107, "judy", "kim", at(6), at(6, 2))
    game_save(judy, at(6, 0, 5), own=(PAUL, JIN))
    game_save(kim, at(6, 0, 6), own=(LAW, LEI))
    play(judy, True, (PAUL, JIN), at(6, 3))
    wait_for_queue()
    report.check(
        7,
        "the opponent quit: named, unseen",
        matches("judy", "kim"),
        [("judy", "kim", 1, [PAUL, JIN], None)],
    )

    leo = state["leo"]
    play(leo, True, (PAUL,), at(7))
    wait_for_queue()
    report.check(8, "no room, no opponent", matches("leo"), [("leo", None, 1, [PAUL], None)])

    mia = state["mia"]
    record(mia, True, (PAUL,))
    record(mia, True, (PAUL,))
    game_save(mia, at(8))
    wait_for_queue()
    report.check(
        9,
        "two wins in one save are counted, not guessed",
        (rows("SELECT merged_count FROM save_states WHERE npid = 'mia'")[0][0], matches("mia")),
        (1, []),
    )

    nick, olga = state["nick"], state["olga"]
    broken = next_data_id()
    write_file(broken, b"short")
    point_row("nick", broken, at(9))
    play(olga, True, (PAUL,), at(9, 0, 1))
    play(nick, True, (PAUL,), at(9, 1))
    wait_for_queue()
    report.check(
        10,
        "an unreadable save holds up nobody and recovers",
        [row[:3] for row in matches("nick", "olga")],
        [("olga", None, 1), ("nick", None, 1)],
    )

    pete, quinn = state["pete"], state["quinn"]
    late = next_data_id()
    game_save(quinn, at(10), data_id=late + 1)
    record(pete, True, (PAUL,))
    game_save(pete, at(10, 0, 1), data_id=late)
    wait_for_queue()
    report.check(11, "a lower data_id committed later", [row[:3] for row in matches("pete")], [("pete", None, 1)])

    # The named players are all taken; bulk ones are still as the seed left them.
    promoted = seeded("bulk0")
    open_room(114, "bulk0", "bulk1", at(13), at(13, 4))
    promoted["ranks"] = {str(PAUL): 20}
    game_save(promoted, at(13, 0, 5), own=(PAUL, PAUL))
    promoted["ranks"] = {str(PAUL): 21}
    play(promoted, True, (PAUL,), at(13, 3))
    wait_for_queue()
    report.check(14, "the rank a match was entered at, not the one it earned", ranks_of("bulk0"), [[20]])

    newcomer = seeded("bulk2")
    newcomer["ranks"] = {str(LAW): 14}
    play(newcomer, True, (LAW,), at(14))
    wait_for_queue()
    report.check(15, "a character's first match takes the rank after it", ranks_of("bulk2"), [[14]])


def during_outage(state):
    rosa, sam = state["rosa"], state["sam"]
    open_room(112, "rosa", "sam", at(11), at(11, 4))
    game_save(rosa, at(11, 0, 5), own=(JIN, PAUL), wait=False)
    game_save(sam, at(11, 0, 6), own=(LAW, NINA), wait=False)
    play(rosa, True, (JIN, PAUL), at(11, 3), wait=False)
    play(sam, False, (LAW, NINA), at(11, 3, 2), wait=False)


def after_outage(state, report):
    wait_for_state("rosa", 0)
    wait_until(lambda: len(matches("rosa", "sam")) == 1, "the match played during the outage", seconds=40)
    report.check(
        12,
        "a match during a save-admin outage is not lost",
        matches("rosa", "sam"),
        [("rosa", "sam", 1, [PAUL, JIN], [LAW, NINA])],
    )


def before_restart(state):
    tina = state["tina"]
    open_room(113, "tina", "alice", at(12), at(12, 8))
    play(tina, True, (PAUL,), at(12, 3))
    play(state["alice"], False, (PAUL,), at(12, 3, 1))
    wait_for_queue()


def after_restart(state, report):
    wait_until(lambda: rows("SELECT 1 FROM save_states LIMIT 1"), "be to answer")
    play(state["tina"], False, (PAUL,), at(12, 6))
    play(state["alice"], True, (PAUL,), at(12, 6, 1))
    wait_for_queue()
    report.check(
        13,
        "a be restart repeats nothing and misses nothing",
        matches("tina"),
        [("tina", "alice", 1, [PAUL], [PAUL]), ("tina", "alice", 2, [PAUL], [PAUL])],
    )
    report.check(
        13,
        "no event ended dead",
        rows("SELECT status, count(*) FROM match_events GROUP BY status"),
        [("done", rows("SELECT count(*) FROM match_events")[0][0])],
    )


def load():
    if not os.path.exists(STATE_PATH):
        return {}
    with open(STATE_PATH) as f:
        return json.load(f)


def main():
    phase = sys.argv[1]
    state = load()
    report = Report()
    if phase == "seed":
        seed(state)
    elif phase == "scenarios":
        scenarios(state, report)
    elif phase == "during-outage":
        during_outage(state)
    elif phase == "after-outage":
        after_outage(state, report)
    elif phase == "before-restart":
        before_restart(state)
    elif phase == "after-restart":
        after_restart(state, report)
    with open(STATE_PATH, "w") as f:
        json.dump(state, f)
    sys.exit(0 if all(line[2] for line in report.lines) else 1)


if __name__ == "__main__":
    main()
