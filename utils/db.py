"""SQLite database for MizoBot: guild settings, mod cases, event log, economy."""
import json
import sqlite3
import time

STARTING_BALANCE = 10_000
DEFAULT_PREFIX = "!"

SCHEMA = """
CREATE TABLE IF NOT EXISTS guilds (
    guild_id        INTEGER PRIMARY KEY,
    name            TEXT,
    prefix          TEXT NOT NULL DEFAULT '!',
    log_channel     INTEGER,
    modlog_channel  INTEGER,
    quarantine_role INTEGER,
    joined_at       INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS cases (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id    INTEGER NOT NULL,
    case_no     INTEGER NOT NULL,
    user_id     INTEGER NOT NULL,
    mod_id      INTEGER NOT NULL,
    action      TEXT NOT NULL,          -- warn kick ban unban mute unmute quarantine unquarantine
    reason      TEXT,
    duration    INTEGER,                -- seconds, for mutes
    active      INTEGER NOT NULL DEFAULT 1,
    created_at  INTEGER NOT NULL,
    UNIQUE (guild_id, case_no)
);
CREATE INDEX IF NOT EXISTS idx_cases_user ON cases (guild_id, user_id);

CREATE TABLE IF NOT EXISTS events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id    INTEGER NOT NULL,
    type        TEXT NOT NULL,
    user_id     INTEGER,
    channel_id  INTEGER,
    detail      TEXT,
    created_at  INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_guild ON events (guild_id, created_at);

CREATE TABLE IF NOT EXISTS quarantined (
    guild_id    INTEGER NOT NULL,
    user_id     INTEGER NOT NULL,
    role_ids    TEXT NOT NULL,
    PRIMARY KEY (guild_id, user_id)
);

CREATE TABLE IF NOT EXISTS users (
    user_id     INTEGER PRIMARY KEY,
    balance     INTEGER NOT NULL,
    last_daily  INTEGER NOT NULL DEFAULT 0,
    won         INTEGER NOT NULL DEFAULT 0,
    lost        INTEGER NOT NULL DEFAULT 0,
    created_at  INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS transactions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id    INTEGER,
    user_id     INTEGER NOT NULL,
    other_id    INTEGER,
    kind        TEXT NOT NULL,          -- give daily coinflip slots
    amount      INTEGER NOT NULL,       -- signed, from user_id's perspective
    created_at  INTEGER NOT NULL
);
"""


class Database:
    def __init__(self, path="mizobot.db"):
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    # ------------------------------------------------------------ guilds
    def ensure_guild(self, guild):
        self.conn.execute(
            "INSERT INTO guilds (guild_id, name, joined_at) VALUES (?, ?, ?) "
            "ON CONFLICT(guild_id) DO UPDATE SET name=excluded.name",
            (guild.id, guild.name, int(time.time())),
        )
        self.conn.commit()

    def get_guild(self, guild_id):
        return self.conn.execute("SELECT * FROM guilds WHERE guild_id=?", (guild_id,)).fetchone()

    def set_guild_field(self, guild_id, field, value):
        assert field in {"prefix", "log_channel", "modlog_channel", "quarantine_role"}
        self.conn.execute(f"UPDATE guilds SET {field}=? WHERE guild_id=?", (value, guild_id))
        self.conn.commit()

    def all_prefixes(self):
        return {r["guild_id"]: r["prefix"] for r in self.conn.execute("SELECT guild_id, prefix FROM guilds")}

    # ------------------------------------------------------------- cases
    def add_case(self, guild_id, user_id, mod_id, action, reason=None, duration=None):
        row = self.conn.execute("SELECT COALESCE(MAX(case_no), 0) + 1 FROM cases WHERE guild_id=?", (guild_id,)).fetchone()
        case_no = row[0]
        self.conn.execute(
            "INSERT INTO cases (guild_id, case_no, user_id, mod_id, action, reason, duration, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (guild_id, case_no, user_id, mod_id, action, reason, duration, int(time.time())),
        )
        self.conn.commit()
        return case_no

    def get_case(self, guild_id, case_no):
        return self.conn.execute("SELECT * FROM cases WHERE guild_id=? AND case_no=?", (guild_id, case_no)).fetchone()

    def user_cases(self, guild_id, user_id, action=None, only_active=False):
        q = "SELECT * FROM cases WHERE guild_id=? AND user_id=?"
        args = [guild_id, user_id]
        if action:
            q += " AND action=?"
            args.append(action)
        if only_active:
            q += " AND active=1"
        return self.conn.execute(q + " ORDER BY case_no DESC", args).fetchall()

    def recent_cases(self, guild_id, limit=10):
        return self.conn.execute(
            "SELECT * FROM cases WHERE guild_id=? ORDER BY case_no DESC LIMIT ?", (guild_id, limit)
        ).fetchall()

    def deactivate_case(self, guild_id, case_no):
        cur = self.conn.execute("UPDATE cases SET active=0 WHERE guild_id=? AND case_no=? AND active=1", (guild_id, case_no))
        self.conn.commit()
        return cur.rowcount > 0

    def clear_warns(self, guild_id, user_id):
        cur = self.conn.execute(
            "UPDATE cases SET active=0 WHERE guild_id=? AND user_id=? AND action='warn' AND active=1",
            (guild_id, user_id),
        )
        self.conn.commit()
        return cur.rowcount

    # ------------------------------------------------------------ events
    def log_event(self, guild_id, type_, user_id=None, channel_id=None, detail=None):
        self.conn.execute(
            "INSERT INTO events (guild_id, type, user_id, channel_id, detail, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (guild_id, type_, user_id, channel_id, (detail or "")[:1500], int(time.time())),
        )
        self.conn.commit()

    def recent_events(self, guild_id, limit=15, type_=None, user_id=None):
        q, args = "SELECT * FROM events WHERE guild_id=?", [guild_id]
        if type_:
            q += " AND type=?"
            args.append(type_)
        if user_id:
            q += " AND user_id=?"
            args.append(user_id)
        return self.conn.execute(q + " ORDER BY id DESC LIMIT ?", (*args, limit)).fetchall()

    # -------------------------------------------------------- quarantine
    def save_quarantine(self, guild_id, user_id, role_ids):
        self.conn.execute(
            "INSERT OR REPLACE INTO quarantined (guild_id, user_id, role_ids) VALUES (?, ?, ?)",
            (guild_id, user_id, json.dumps(role_ids)),
        )
        self.conn.commit()

    def pop_quarantine(self, guild_id, user_id):
        row = self.conn.execute("SELECT role_ids FROM quarantined WHERE guild_id=? AND user_id=?", (guild_id, user_id)).fetchone()
        if row is None:
            return None
        self.conn.execute("DELETE FROM quarantined WHERE guild_id=? AND user_id=?", (guild_id, user_id))
        self.conn.commit()
        return json.loads(row["role_ids"])

    def is_quarantined(self, guild_id, user_id):
        return self.conn.execute(
            "SELECT 1 FROM quarantined WHERE guild_id=? AND user_id=?", (guild_id, user_id)
        ).fetchone() is not None

    # ----------------------------------------------------------- economy
    def get_user(self, user_id):
        self.conn.execute(
            "INSERT OR IGNORE INTO users (user_id, balance, created_at) VALUES (?, ?, ?)",
            (user_id, STARTING_BALANCE, int(time.time())),
        )
        self.conn.commit()
        return self.conn.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()

    def balance(self, user_id):
        return self.get_user(user_id)["balance"]

    def spend(self, user_id, amount):
        """Atomically deduct `amount`. Returns False if the user can't afford it."""
        self.get_user(user_id)
        cur = self.conn.execute(
            "UPDATE users SET balance = balance - ? WHERE user_id=? AND balance >= ?", (amount, user_id, amount)
        )
        self.conn.commit()
        return cur.rowcount == 1

    def add(self, user_id, amount):
        self.get_user(user_id)
        self.conn.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", (amount, user_id))
        self.conn.commit()

    def record_result(self, user_id, net):
        col = "won" if net > 0 else "lost"
        self.conn.execute(f"UPDATE users SET {col} = {col} + ? WHERE user_id=?", (abs(net), user_id))
        self.conn.commit()

    def transfer(self, from_id, to_id, amount):
        if not self.spend(from_id, amount):
            return False
        self.add(to_id, amount)
        return True

    def add_transaction(self, guild_id, user_id, kind, amount, other_id=None):
        self.conn.execute(
            "INSERT INTO transactions (guild_id, user_id, other_id, kind, amount, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (guild_id, user_id, other_id, kind, amount, int(time.time())),
        )
        self.conn.commit()

    def richest(self, limit=10):
        return self.conn.execute("SELECT user_id, balance FROM users ORDER BY balance DESC LIMIT ?", (limit,)).fetchall()
