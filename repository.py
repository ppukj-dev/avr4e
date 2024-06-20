import sqlite3


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
            UNIQUE (guild_id, user_id)
        )""")
        self.cursor.close()
        self.connection.close()

    def get_character(self, guild_id: str, user_id: str) -> tuple:
        query = """
        SELECT
            character_name,
            data
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
            actions: str
            ) -> None:
        query = """
        INSERT INTO character_user_map (
            guild_id, user_id, character_name, data, actions
        )
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT (guild_id, user_id)
            DO UPDATE SET
                character_name = ?,
                data = ?,
                actions = ?
        """

        with self as db:
            db.cursor.execute(query, (
                guild_id, user_id,
                character_name, data, actions,
                character_name, data, actions))
            db.connection.commit()

    def get_actions(self, guild_id: str, user_id: str) -> tuple:
        query = """
        SELECT
            character_name,
            actions
        FROM character_user_map
        WHERE guild_id = ? AND user_id = ?
        """

        with self as db:
            db.cursor.execute(query, (guild_id, user_id))
            result = db.cursor.fetchone()

        return result
