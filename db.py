import sqlite3
from contextlib import contextmanager


class Database:
    def __init__(self, path: str):
        self.path = path
        self._init_db()

    @contextmanager
    def conn(self):
        c = sqlite3.connect(self.path)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA foreign_keys = ON")
        try:
            yield c
            c.commit()
        except Exception:
            c.rollback()
            raise
        finally:
            c.close()

    def _init_db(self):
        with self.conn() as c:
            c.executescript("""
                CREATE TABLE IF NOT EXISTS telegram_users (
                    telegram_user_id INTEGER PRIMARY KEY,
                    telegram_name TEXT NOT NULL,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS members (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    group_id INTEGER NOT NULL,
                    display_name TEXT NOT NULL,
                    telegram_user_id INTEGER REFERENCES telegram_users(telegram_user_id),
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(group_id, display_name),
                    UNIQUE(group_id, telegram_user_id)
                );

                CREATE TABLE IF NOT EXISTS expenses (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    group_id INTEGER NOT NULL,
                    payer_member_id INTEGER NOT NULL REFERENCES members(id),
                    payer_name TEXT NOT NULL,
                    amount REAL NOT NULL,
                    description TEXT NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS expense_splits (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    expense_id INTEGER NOT NULL REFERENCES expenses(id) ON DELETE CASCADE,
                    member_id INTEGER NOT NULL REFERENCES members(id),
                    share REAL NOT NULL,
                    settled INTEGER DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS settlements (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    group_id INTEGER NOT NULL,
                    from_member_id INTEGER NOT NULL REFERENCES members(id),
                    to_member_id INTEGER NOT NULL REFERENCES members(id),
                    amount REAL NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
            """)

    def upsert_telegram_user(self, telegram_user_id: int, telegram_name: str):
        with self.conn() as c:
            c.execute("""
                INSERT INTO telegram_users (telegram_user_id, telegram_name)
                VALUES (?, ?)
                ON CONFLICT(telegram_user_id) DO UPDATE SET
                    telegram_name = excluded.telegram_name,
                    updated_at = CURRENT_TIMESTAMP
            """, (telegram_user_id, telegram_name))

    def add_member(self, group_id: int, display_name: str) -> int:
        display_name = display_name.strip()
        if not display_name:
            raise ValueError("Display name cannot be empty.")

        with self.conn() as c:
            existing = c.execute("""
                SELECT id FROM members
                WHERE group_id = ? AND lower(display_name) = lower(?)
            """, (group_id, display_name)).fetchone()
            if existing:
                raise ValueError("That member name already exists in this group.")

            cur = c.execute("""
                INSERT INTO members (group_id, display_name)
                VALUES (?, ?)
            """, (group_id, display_name))
            return cur.lastrowid

    def get_members(self, group_id: int) -> list[dict]:
        with self.conn() as c:
            rows = c.execute("""
                SELECT id, group_id, display_name, telegram_user_id, created_at
                FROM members
                WHERE group_id = ?
                ORDER BY lower(display_name), id
            """, (group_id,)).fetchall()
        return [dict(r) for r in rows]

    def get_member(self, group_id: int, member_id: int) -> dict | None:
        with self.conn() as c:
            row = c.execute("""
                SELECT id, group_id, display_name, telegram_user_id, created_at
                FROM members
                WHERE group_id = ? AND id = ?
            """, (group_id, member_id)).fetchone()
        return dict(row) if row else None

    def get_member_by_telegram_user(self, group_id: int, telegram_user_id: int) -> dict | None:
        with self.conn() as c:
            row = c.execute("""
                SELECT id, group_id, display_name, telegram_user_id, created_at
                FROM members
                WHERE group_id = ? AND telegram_user_id = ?
            """, (group_id, telegram_user_id)).fetchone()
        return dict(row) if row else None

    def get_member_by_telegram_name(self, group_id: int, telegram_name_lower: str) -> dict | None:
        with self.conn() as c:
            row = c.execute("""
                SELECT m.id, m.group_id, m.display_name, m.telegram_user_id, m.created_at
                FROM members m
                JOIN telegram_users tu
                  ON tu.telegram_user_id = m.telegram_user_id
                WHERE m.group_id = ?
                  AND lower(tu.telegram_name) = lower(?)
            """, (group_id, telegram_name_lower)).fetchone()
        return dict(row) if row else None

    def link_member_to_telegram_user(
        self,
        group_id: int,
        member_id: int,
        telegram_user_id: int,
        telegram_name: str,
    ):
        with self.conn() as c:
            self._upsert_telegram_user_with_conn(c, telegram_user_id, telegram_name)

            existing_link = c.execute("""
                SELECT id, display_name
                FROM members
                WHERE group_id = ? AND telegram_user_id = ?
            """, (group_id, telegram_user_id)).fetchone()
            if existing_link and existing_link["id"] != member_id:
                raise ValueError(
                    f"You're already linked to #{existing_link['id']} {existing_link['display_name']}."
                )

            target = c.execute("""
                SELECT id
                FROM members
                WHERE group_id = ? AND id = ?
            """, (group_id, member_id)).fetchone()
            if not target:
                raise ValueError("Member not found in this group.")

            try:
                c.execute("""
                    UPDATE members
                    SET telegram_user_id = ?
                    WHERE group_id = ? AND id = ?
                """, (telegram_user_id, group_id, member_id))
            except sqlite3.IntegrityError:
                raise ValueError("That member is already linked to another Telegram user.")

    def _upsert_telegram_user_with_conn(self, c, telegram_user_id: int, telegram_name: str):
        c.execute("""
            INSERT INTO telegram_users (telegram_user_id, telegram_name)
            VALUES (?, ?)
            ON CONFLICT(telegram_user_id) DO UPDATE SET
                telegram_name = excluded.telegram_name,
                updated_at = CURRENT_TIMESTAMP
        """, (telegram_user_id, telegram_name))

    def add_expense(
        self,
        group_id: int,
        payer_member_id: int,
        payer_name: str,
        amount: float,
        desc: str,
        splits: dict[int, float],
    ) -> int:
        with self.conn() as c:
            payer = c.execute("""
                SELECT id FROM members
                WHERE id = ? AND group_id = ?
            """, (payer_member_id, group_id)).fetchone()
            if not payer:
                raise ValueError("Payer member not found in this group.")

            member_ids = list(splits.keys())
            if not member_ids:
                raise ValueError("No split members selected.")

            rows = c.execute(f"""
                SELECT id FROM members
                WHERE group_id = ?
                  AND id IN ({",".join("?" for _ in member_ids)})
            """, [group_id, *member_ids]).fetchall()

            if len(rows) != len(member_ids):
                raise ValueError("One or more selected members are not in this group.")

            cur = c.execute("""
                INSERT INTO expenses (group_id, payer_member_id, payer_name, amount, description)
                VALUES (?, ?, ?, ?, ?)
            """, (group_id, payer_member_id, payer_name, amount, desc))
            expense_id = cur.lastrowid

            c.executemany("""
                INSERT INTO expense_splits (expense_id, member_id, share)
                VALUES (?, ?, ?)
            """, [(expense_id, mid, share) for mid, share in splits.items()])

            return expense_id

    def get_expenses(self, group_id: int, limit: int = 10) -> list[dict]:
        with self.conn() as c:
            rows = c.execute("""
                SELECT id, payer_member_id, payer_name, amount, description AS desc, created_at
                FROM expenses
                WHERE group_id = ?
                ORDER BY id DESC
                LIMIT ?
            """, (group_id, limit)).fetchall()
        return [dict(r) for r in rows]

    def delete_expense(self, group_id: int, expense_id: int, requester_member_id: int) -> bool:
        with self.conn() as c:
            row = c.execute("""
                SELECT id
                FROM expenses
                WHERE id = ? AND group_id = ? AND payer_member_id = ?
            """, (expense_id, group_id, requester_member_id)).fetchone()

            if not row:
                return False

            c.execute("DELETE FROM expenses WHERE id = ?", (expense_id,))
            return True

    def delete_latest_expense_by_payer(self, group_id: int, payer_member_id: int) -> dict | None:
        with self.conn() as c:
            row = c.execute("""
                SELECT id, description AS desc, amount
                FROM expenses
                WHERE group_id = ? AND payer_member_id = ?
                ORDER BY id DESC
                LIMIT 1
            """, (group_id, payer_member_id)).fetchone()

            if not row:
                return None

            c.execute("DELETE FROM expenses WHERE id = ?", (row["id"],))
            return dict(row)

    def get_balances(self, group_id: int) -> dict[tuple[int, int], float]:
        with self.conn() as c:
            rows = c.execute("""
                SELECT e.payer_member_id, es.member_id AS debtor_member_id, es.share
                FROM expense_splits es
                JOIN expenses e ON e.id = es.expense_id
                WHERE e.group_id = ?
                  AND es.settled = 0
                  AND e.payer_member_id != es.member_id
            """, (group_id,)).fetchall()

        from collections import defaultdict

        net = defaultdict(lambda: defaultdict(float))
        for row in rows:
            payer = row["payer_member_id"]
            debtor = row["debtor_member_id"]
            share = row["share"]
            net[debtor][payer] += share
            net[payer][debtor] -= share

        result = {}
        seen = set()

        for a, others in net.items():
            for b, amount in others.items():
                pair = tuple(sorted((a, b)))
                if pair in seen:
                    continue
                seen.add(pair)

                net_ab = net[a][b]
                if net_ab > 0.005:
                    result[(a, b)] = round(net_ab, 2)
                elif net_ab < -0.005:
                    result[(b, a)] = round(-net_ab, 2)

        return result

    def settle_between(self, group_id: int, from_member_id: int, to_member_id: int) -> float:
        with self.conn() as c:
            rows = c.execute("""
                SELECT es.id, es.share
                FROM expense_splits es
                JOIN expenses e ON e.id = es.expense_id
                WHERE e.group_id = ?
                  AND e.payer_member_id = ?
                  AND es.member_id = ?
                  AND es.settled = 0
            """, (group_id, to_member_id, from_member_id)).fetchall()

            total = round(sum(r["share"] for r in rows), 2)
            ids = [r["id"] for r in rows]

            if ids:
                placeholders = ",".join("?" for _ in ids)
                c.execute(
                    f"UPDATE expense_splits SET settled = 1 WHERE id IN ({placeholders})",
                    ids,
                )

            if total > 0:
                c.execute("""
                    INSERT INTO settlements (group_id, from_member_id, to_member_id, amount)
                    VALUES (?, ?, ?, ?)
                """, (group_id, from_member_id, to_member_id, total))

            return total

    def get_member_by_name(self, group_id: int, display_name: str) -> dict | None:
        with self.conn() as c:
            row = c.execute("""
                SELECT id, group_id, display_name, telegram_user_id, created_at
                FROM members
                WHERE group_id = ?
                AND lower(display_name) = lower(?)
            """, (group_id, display_name.strip())).fetchone()
        return dict(row) if row else None

    def get_expenses_by_payer(self, group_id: int, member_id: int, limit: int = 20):
        with self.conn() as c:
            rows = c.execute("""
                SELECT id, description AS desc, amount, created_at
                FROM expenses
                WHERE group_id = ? AND payer_member_id = ?
                ORDER BY id DESC
                LIMIT ?
            """, (group_id, member_id, limit)).fetchall()
        return [dict(r) for r in rows]
