from dataclasses import dataclass
from enum import Enum
from typing import Optional

import pymysql

from app.core.mysql.MySQLTable import MySQLTable
pymysql.install_as_MySQLdb()
import MySQLdb

from app.core.mysql.MySQLConnectionProvider import MySQLConnectionProvider


class ThresholdMethod(str, Enum):
    PROTECTED = "PROTECTED"
    EXPOSED = "EXPOSED"

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class Threshold:
    method: ThresholdMethod | str
    threshold: int
    id: Optional[int] = None

    def normalized(self) -> "Threshold":
        if isinstance(self.method, ThresholdMethod):
            method_enum = self.method
        else:
            method_enum = ThresholdMethod(str(self.method).strip().upper())
        return Threshold(
            method=method_enum,
            threshold=int(self.threshold),
            id=self.id,
        )


class ThresholdManager:
    def __init__(self):
        self.connection = MySQLConnectionProvider.get_instance().get_connection()
        self.cursor = self.connection.cursor(MySQLdb.cursors.DictCursor)

    def complete(self):
        try:
            self.cursor.close()
        finally:
            self.connection.close()

    def _validate_threshold(self, threshold: Threshold) -> Threshold:
        t = threshold.normalized()
        if t.method not in (ThresholdMethod.PROTECTED, ThresholdMethod.EXPOSED):
            raise ValueError("threshold method must be PROTECTED or EXPOSED")
        return t

    def get_or_create(self, threshold: Threshold) -> Threshold:
        t = self._validate_threshold(threshold)

        try:
            self.cursor.execute(
                f"""
                SELECT id
                FROM {MySQLTable.THRESHOLD_CONFIGS}
                WHERE method = %s AND threshold = %s
                LIMIT 1
                """,
                (t.method.value, t.threshold),
            )
            row = self.cursor.fetchone()
            if row:
                return Threshold(method=t.method, threshold=t.threshold, id=int(row["id"]))

            self.cursor.execute(
                f"""
                INSERT INTO {MySQLTable.THRESHOLD_CONFIGS} (method, threshold)
                VALUES (%s, %s)
                """,
                (t.method.value, t.threshold),
            )
            self.connection.commit()
            return Threshold(method=t.method, threshold=t.threshold, id=int(self.cursor.lastrowid))

        except Exception:
            self.connection.rollback()
            raise

    def get_if_exists(self, threshold: Threshold) -> Optional[Threshold]:
        t = self._validate_threshold(threshold)

        self.cursor.execute(
            f"""
            SELECT id
            FROM {MySQLTable.THRESHOLD_CONFIGS}
            WHERE method = %s AND threshold = %s
            LIMIT 1
            """,
            (t.method.value, t.threshold),
        )
        row = self.cursor.fetchone()
        if not row:
            return None
        return Threshold(method=t.method, threshold=t.threshold, id=int(row["id"]))
