import os
import sqlite3
import mysql.connector
import dotenv
import datetime

dotenv.load_dotenv()
MYSQL_HOST = os.getenv("MYSQL_HOST")
MYSQL_USER = os.getenv("MYSQL_USER")
MYSQL_PASS = os.getenv("MYSQL_PASS")
MYSQL_DB = "db_4e"


class Repository:
    def __init__(self):
        pass

    def __enter__(self):
        self.connection = sqlite3.connect("database/avr4e.db")
        self.cursor = self.connection.cursor()
        return self

    def __exit__(self, type, value, traceback):
        self.cursor.close()
        self.connection.close()


class CharacterUserMapRepository(Repository):
    def __init__(self):
        super().__init__()
        self.connection = sqlite3.connect("database/avr4e.db")
        self.cursor = self.connection.cursor()
        self.cursor.execute("""
        CREATE TABLE IF NOT EXISTS character_user_map (
            id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
            guild_id VARCHAR(255) NOT NULL,
            user_id VARCHAR(255) NOT NULL,
            character_name VARCHAR(255) NOT NULL,
            data TEXT NOT NULL,
            actions TEXT NOT NULL,
            sheet_url TEXT NOT NULL,
            UNIQUE (guild_id, user_id)
        )""")
        self.cursor.close()
        self.connection.close()

    def get_character(self, guild_id: str, user_id: str) -> tuple:
        query = """
        SELECT
            id,
            character_name,
            data,
            actions,
            sheet_url
        FROM character_user_map
        WHERE guild_id = ? AND user_id = ?
        LIMIT 1
        """

        with self as db:
            db.cursor.execute(query, (guild_id, user_id))
            result = db.cursor.fetchone()

        return result

    def set_character(
            self,
            guild_id: str,
            user_id: str,
            character_name: str,
            data: str,
            actions: str,
            sheet_url: str
            ) -> None:
        query = """
        INSERT INTO character_user_map (
            guild_id, user_id, character_name, data, actions,
            sheet_url
        )
        VALUES (
            ?, ?, ?, ?, ?,
            ?
        )
        ON CONFLICT (guild_id, user_id)
            DO UPDATE SET
                character_name = ?,
                data = ?,
                actions = ?,
                sheet_url = ?
        """

        with self as db:
            db.cursor.execute(query, (
                guild_id, user_id,
                character_name, data, actions, sheet_url,
                character_name, data, actions, sheet_url))
            db.connection.commit()

    def update_character(self, id: int, data: str, actions: str) -> None:
        query = """
        UPDATE character_user_map
        SET
            data = COALESCE(?, data),
            actions = COALESCE(?, actions)
        WHERE id = ?
        """

        with self as db:
            db.cursor.execute(query, (data, actions, id))
            db.connection.commit()


class GachaMapRepository(Repository):
    def __init__(self):
        super().__init__()
        self.connection = sqlite3.connect("database/avr4e.db")
        self.cursor = self.connection.cursor()
        self.cursor.execute("""
        CREATE TABLE IF NOT EXISTS gacha_map (
            id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
            guild_id VARCHAR(255) NOT NULL,
            start TEXT NOT NULL,
            items TEXT NOT NULL,
            sheet_url TEXT NOT NULL,
            UNIQUE (guild_id)
        )""")
        self.cursor.close()
        self.connection.close()

    def get_gacha(self, guild_id: str) -> tuple:
        query = """
        SELECT
            id,
            guild_id,
            start,
            items,
            sheet_url
        FROM gacha_map
        WHERE guild_id = ?
        LIMIT 1
        """

        with self as db:
            db.cursor.execute(query, (guild_id,))
            result = db.cursor.fetchone()

        return result

    def set_gacha(
            self,
            guild_id: str,
            start: str,
            items: str,
            sheet_url: str
            ) -> None:
        query = """
        INSERT INTO gacha_map (
            guild_id, start, items, sheet_url
        )
        VALUES (
            ?, ?, ?, ?
        )
        ON CONFLICT (guild_id)
            DO UPDATE SET
                start = ?,
                items = ?,
                sheet_url = ?
        """

        with self as db:
            db.cursor.execute(query, (
                guild_id,
                start, items, sheet_url,
                start, items, sheet_url))
            db.connection.commit()

    def update_character(self, id: int, start: str, items: str) -> None:
        query = """
        UPDATE gacha_map
        SET
            start = COALESCE(?, start),
            items = COALESCE(?, items)
        WHERE id = ?
        """

        with self as db:
            db.cursor.execute(query, (start, items, id))
            db.connection.commit()


class DowntimeMapRepository(Repository):
    def __init__(self):
        super().__init__()
        self.connection = sqlite3.connect("database/avr4e.db")
        self.cursor = self.connection.cursor()
        self.cursor.execute("""
        CREATE TABLE IF NOT EXISTS downtime_map (
            id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
            guild_id VARCHAR(255) NOT NULL,
            start TEXT NOT NULL,
            items TEXT NOT NULL,
            sheet_url TEXT NOT NULL,
            UNIQUE (guild_id)
        )""")
        self.cursor.close()
        self.connection.close()

    def get_gacha(self, guild_id: str) -> tuple:
        query = """
        SELECT
            id,
            guild_id,
            start,
            items,
            sheet_url
        FROM downtime_map
        WHERE guild_id = ?
        LIMIT 1
        """

        with self as db:
            db.cursor.execute(query, (guild_id,))
            result = db.cursor.fetchone()

        return result

    def set_gacha(
            self,
            guild_id: str,
            start: str,
            items: str,
            sheet_url: str
            ) -> None:
        query = """
        INSERT INTO downtime_map (
            guild_id, start, items, sheet_url
        )
        VALUES (
            ?, ?, ?, ?
        )
        ON CONFLICT (guild_id)
            DO UPDATE SET
                start = ?,
                items = ?,
                sheet_url = ?
        """

        with self as db:
            db.cursor.execute(query, (
                guild_id,
                start, items, sheet_url,
                start, items, sheet_url))
            db.connection.commit()

    def update_character(self, id: int, start: str, items: str) -> None:
        query = """
        UPDATE downtime_map
        SET
            start = COALESCE(?, start),
            items = COALESCE(?, items)
        WHERE id = ?
        """

        with self as db:
            db.cursor.execute(query, (start, items, id))
            db.connection.commit()


class MySQLRepository:
    def __init__(self):
        self.host = MYSQL_HOST
        self.user = MYSQL_USER
        self.password = MYSQL_PASS
        self.database = MYSQL_DB

    def __enter__(self):
        self.connection = mysql.connector.connect(
            host=self.host,
            user=self.user,
            password=self.password,
            database=self.database
        )
        self.cursor = self.connection.cursor()
        return self

    def __exit__(self, type, value, traceback):
        self.cursor.close()
        self.connection.close()


class MonsterListRepository(MySQLRepository):
    def __init__(self):
        super().__init__()

    def get_monster_list(self):
        query = "SELECT * FROM monster_list LIMIT 10"
        with self as db:
            db.cursor.execute(query)
            result = db.cursor.fetchall()
        return result

    def get_monsters_by_levels(self, levels: list):
        query = (
            "SELECT"
            "   id, name, level, role, `group`, size, type, source, xp "
            "FROM monster_list WHERE level IN (%s)"
            % ','.join(['%s'] * len(levels))
        )
        with self as db:
            db.cursor.execute(query, tuple(levels))
            result = db.cursor.fetchall()
        return result

    def get_monsters_by_levels_and_roles(self, levels: list, roles: list):
        level_placeholders = ','.join(['%s'] * len(levels))
        role_conditions = ' OR '.join(['role LIKE %s' for _ in roles])

        query = (
            f"SELECT "
            f"  id, name, level, role, `group`, "
            f"  size, type, source, description, xp "
            f"FROM monster_list "
            f"WHERE level IN ({level_placeholders}) AND ({role_conditions})"
        )

        # Prepare values: levels stay the same, roles are formatted for LIKE
        values = tuple(levels) + tuple(f"%{role}%" for role in roles)

        with self as db:
            db.cursor.execute(query, values)
            result = db.cursor.fetchall()
        return result

    def get_monsters_by_levels_roles_and_keywords(
            self, levels: list, roles: list, keywords: list):
        level_placeholders = ','.join(['%s'] * len(levels))
        role_conditions = ' OR '.join(['role LIKE %s' for _ in roles])
        keyword_conditions = ' AND '.join(
            ["description LIKE %s" for _ in keywords])

        # Construct the full query with levels, roles, and keywords
        query = (
            f"SELECT "
            f"  id, name, level, role, `group`, "
            f"  size, type, source, xp "
            f"FROM monster_list "
            f"WHERE level IN ({level_placeholders}) AND ({role_conditions})"
            f" AND ({keyword_conditions})"
        )

        values = (
            tuple(levels) +
            tuple(f"%{role}%" for role in roles) +
            tuple(f"%{keyword}%" for keyword in keywords)
        )

        with self as db:
            db.cursor.execute(query, values)
            result = db.cursor.fetchall()
        return result


class MonstersUserMapRepository(Repository):
    def __init__(self):
        super().__init__()
        self.connection = sqlite3.connect("database/avr4e.db")
        self.cursor = self.connection.cursor()
        self.cursor.execute("""
        CREATE TABLE IF NOT EXISTS monsters_user_map (
            id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
            guild_id VARCHAR(255) NOT NULL,
            user_id VARCHAR(255) NOT NULL,
            character_name VARCHAR(255) NOT NULL,
            data TEXT NOT NULL,
            actions TEXT NOT NULL,
            sheet_url TEXT NOT NULL,
            UNIQUE (guild_id, user_id)
        )""")
        self.cursor.close()
        self.connection.close()

    def get_character(self, guild_id: str, user_id: str) -> tuple:
        query = """
        SELECT
            id,
            character_name,
            data,
            actions,
            sheet_url
        FROM monsters_user_map
        WHERE guild_id = ? AND user_id = ?
        LIMIT 1
        """

        with self as db:
            db.cursor.execute(query, (guild_id, user_id))
            result = db.cursor.fetchone()

        return result

    def set_character(
            self,
            guild_id: str,
            user_id: str,
            character_name: str,
            data: str,
            actions: str,
            sheet_url: str
            ) -> None:
        query = """
        INSERT INTO monsters_user_map (
            guild_id, user_id, character_name, data, actions,
            sheet_url
        )
        VALUES (
            ?, ?, ?, ?, ?,
            ?
        )
        ON CONFLICT (guild_id, user_id)
            DO UPDATE SET
                character_name = ?,
                data = ?,
                actions = ?,
                sheet_url = ?
        """

        with self as db:
            db.cursor.execute(query, (
                guild_id, user_id,
                character_name, data, actions, sheet_url,
                character_name, data, actions, sheet_url))
            db.connection.commit()

    def update_character(self, id: int, data: str, actions: str) -> None:
        query = """
        UPDATE monsters_user_map
        SET
            data = COALESCE(?, data),
            actions = COALESCE(?, actions)
        WHERE id = ?
        """

        with self as db:
            db.cursor.execute(query, (data, actions, id))
            db.connection.commit()


class BetaEventMapRepository(Repository):
    def __init__(self):
        super().__init__()
        self.connection = sqlite3.connect("database/avr4e.db")
        self.cursor = self.connection.cursor()
        self.cursor.execute("""
        CREATE TABLE IF NOT EXISTS beta_event_map (
            id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
            guild_id VARCHAR(255) NOT NULL,
            items TEXT NOT NULL,
            sheet_url TEXT NOT NULL,
            UNIQUE (guild_id)
        )""")
        self.cursor.close()
        self.connection.close()

    def get_gacha(self, guild_id: str) -> tuple:
        query = """
        SELECT
            id,
            guild_id,
            items,
            sheet_url
        FROM beta_event_map
        WHERE guild_id = ?
        LIMIT 1
        """

        with self as db:
            db.cursor.execute(query, (guild_id,))
            result = db.cursor.fetchone()

        return result

    def set_gacha(
            self,
            guild_id: str,
            items: str,
            sheet_url: str
            ) -> None:
        query = """
        INSERT INTO beta_event_map (
            guild_id, items, sheet_url
        )
        VALUES (
            ?, ?, ?
        )
        ON CONFLICT (guild_id)
            DO UPDATE SET
                items = ?,
                sheet_url = ?
        """

        with self as db:
            db.cursor.execute(query, (
                guild_id,
                items, sheet_url,
                items, sheet_url))
            db.connection.commit()


class InitiativeRepository(Repository):
    def __init__(self):
        super().__init__()
        self.connection = sqlite3.connect("database/avr4e.db")
        self.cursor = self.connection.cursor()
        self.cursor.execute("""
        CREATE TABLE IF NOT EXISTS initiative (
            id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
            guild_id VARCHAR(255) NOT NULL,
            channel_id VARCHAR(255) NOT NULL,
            current_turn INTEGER NOT NULL DEFAULT 0,
            round INTEGER NOT NULL DEFAULT 0,
            active INTEGER NOT NULL DEFAULT 0,
            started INTEGER NOT NULL DEFAULT 0,
            pinned_message_id VARCHAR(255),
            manual_order_override INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL,
            UNIQUE (guild_id, channel_id)
        )""")
        try:
            self.cursor.execute("""
            ALTER TABLE initiative
            ADD COLUMN manual_order_override INTEGER NOT NULL DEFAULT 0
            """)
        except sqlite3.OperationalError:
            pass
        self.cursor.execute("""
        CREATE TABLE IF NOT EXISTS initiative_combatants (
            id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
            guild_id VARCHAR(255) NOT NULL,
            channel_id VARCHAR(255) NOT NULL,
            name VARCHAR(255) NOT NULL,
            name_key VARCHAR(255) NOT NULL,
            initiative INTEGER NOT NULL,
            modifier INTEGER NOT NULL,
            ac VARCHAR(255),
            fort VARCHAR(255),
            ref VARCHAR(255),
            will VARCHAR(255),
            author_id VARCHAR(255),
            source VARCHAR(32) NOT NULL,
            join_order INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE (guild_id, channel_id, name_key)
        )""")
        self.cursor.close()
        self.connection.close()

    def get_state(self, guild_id: str, channel_id: str) -> tuple:
        query = """
        SELECT
            id,
            guild_id,
            channel_id,
            current_turn,
            round,
            active,
            started,
            pinned_message_id,
            manual_order_override,
            updated_at
        FROM initiative
        WHERE guild_id = ? AND channel_id = ?
        LIMIT 1
        """

        with self as db:
            db.cursor.execute(query, (guild_id, channel_id))
            result = db.cursor.fetchone()

        return result

    def upsert_state(
            self,
            guild_id: str,
            channel_id: str,
            current_turn: int,
            round: int,
            active: int,
            started: int,
            pinned_message_id: str,
            manual_order_override: int
            ) -> None:
        query = """
        INSERT INTO initiative (
            guild_id,
            channel_id,
            current_turn,
            round,
            active,
            started,
            pinned_message_id,
            manual_order_override,
            updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (guild_id, channel_id)
            DO UPDATE SET
                current_turn = ?,
                round = ?,
                active = ?,
                started = ?,
                pinned_message_id = ?,
                manual_order_override = ?,
                updated_at = ?
        """

        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self as db:
            db.cursor.execute(query, (
                guild_id, channel_id, current_turn, round,
                active, started, pinned_message_id, manual_order_override, now,
                current_turn, round, active, started, pinned_message_id,
                manual_order_override, now))
            db.connection.commit()

    def list_combatants(self, guild_id: str, channel_id: str) -> list:
        query = """
        SELECT
            name,
            name_key,
            initiative,
            modifier,
            ac,
            fort,
            ref,
            will,
            author_id,
            source,
            join_order,
            created_at
        FROM initiative_combatants
        WHERE guild_id = ? AND channel_id = ?
        ORDER BY join_order ASC
        """

        with self as db:
            db.cursor.execute(query, (guild_id, channel_id))
            result = db.cursor.fetchall()

        return result

    def get_combatant(
            self,
            guild_id: str,
            channel_id: str,
            name_key: str
            ) -> tuple:
        query = """
        SELECT
            name,
            name_key,
            initiative,
            modifier,
            ac,
            fort,
            ref,
            will,
            author_id,
            source,
            join_order,
            created_at
        FROM initiative_combatants
        WHERE guild_id = ? AND channel_id = ? AND name_key = ?
        LIMIT 1
        """

        with self as db:
            db.cursor.execute(query, (guild_id, channel_id, name_key))
            result = db.cursor.fetchone()

        return result

    def upsert_combatant(
            self,
            guild_id: str,
            channel_id: str,
            name: str,
            name_key: str,
            initiative: int,
            modifier: int,
            ac: str,
            fort: str,
            ref: str,
            will: str,
            author_id: str,
            source: str,
            join_order: int
            ) -> None:
        query = """
        INSERT INTO initiative_combatants (
            guild_id,
            channel_id,
            name,
            name_key,
            initiative,
            modifier,
            ac,
            fort,
            ref,
            will,
            author_id,
            source,
            join_order,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (guild_id, channel_id, name_key)
            DO UPDATE SET
                name = ?,
                initiative = ?,
                modifier = ?,
                ac = ?,
                fort = ?,
                ref = ?,
                will = ?,
                author_id = ?,
                source = ?,
                join_order = ?
        """

        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self as db:
            db.cursor.execute(query, (
                guild_id, channel_id, name, name_key, initiative, modifier,
                ac, fort, ref, will, author_id, source, join_order, now,
                name, initiative, modifier, ac, fort, ref, will,
                author_id, source, join_order))
            db.connection.commit()

    def delete_combatant(
            self,
            guild_id: str,
            channel_id: str,
            name_key: str
            ) -> None:
        query = """
        DELETE FROM initiative_combatants
        WHERE guild_id = ? AND channel_id = ? AND name_key = ?
        """

        with self as db:
            db.cursor.execute(query, (guild_id, channel_id, name_key))
            db.connection.commit()

    def delete_all_combatants(self, guild_id: str, channel_id: str) -> None:
        query = """
        DELETE FROM initiative_combatants
        WHERE guild_id = ? AND channel_id = ?
        """

        with self as db:
            db.cursor.execute(query, (guild_id, channel_id))
            db.connection.commit()

    def get_next_join_order(self, guild_id: str, channel_id: str) -> int:
        query = """
        SELECT MAX(join_order)
        FROM initiative_combatants
        WHERE guild_id = ? AND channel_id = ?
        """

        with self as db:
            db.cursor.execute(query, (guild_id, channel_id))
            result = db.cursor.fetchone()
        if result is None or result[0] is None:
            return 1
        return int(result[0]) + 1
