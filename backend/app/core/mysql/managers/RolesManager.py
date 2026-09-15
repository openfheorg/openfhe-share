'''
User roles will be used to determine access to functionality. 
This class returns information from the roles table. 
It’s a simple wrapper around role lookups so that other code 
doesn’t need to write raw SQL directly.

This class will cache results since the id should be something that doesn't change.
'''

import pymysql
pymysql.install_as_MySQLdb()
import MySQLdb

from app.core.mysql.MySQLTable import MySQLTable
from app.core.mysql.MySQLConnectionProvider import MySQLConnectionProvider

from enum import Enum

class RolesManager:
    # Cache for role_id → role_name lookups
    _role_name_cache: dict[int, str] = {}

    def __init__(self):
        self.connection = MySQLConnectionProvider.get_instance().get_connection()
        self.cursor = self.connection.cursor(MySQLdb.cursors.DictCursor)

    def complete(self):
        try:
            self.cursor.close()
        finally:
            self.connection.close()

    def get_role_name(self, role_id: int) -> str:
        # Check cache first
        if role_id in self._role_name_cache:
            return self._role_name_cache[role_id]

        # Query DB if not cached
        self.cursor.execute(
            f"""
            SELECT name
            FROM {MySQLTable.USER_ROLES}
            WHERE id = %s
            LIMIT 1
            """,
            (role_id,),
        )
        row = self.cursor.fetchone()
        if row:
            role_name = row["name"]
            self._role_name_cache[role_id] = role_name
            return role_name
        return None
