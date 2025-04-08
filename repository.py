import os
import sqlite3
import mysql.connector
import dotenv

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
