import pymysql

from app.core.mysql.MySQLTable import MySQLTable
pymysql.install_as_MySQLdb()
import MySQLdb

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from app.core.mysql.MySQLConnectionProvider import MySQLConnectionProvider


@dataclass
class CryptoAudit:
    nvflare_job_id: str
    security_level: str
    ring_dimension: int
    batch_size: int
    scale_mod_size: int
    multiplicative_depth: int
    scaling_technique: str
    keyswitch_technique: str
    ckks_data_type: str
    ind_cpa_noise_bits: int


class CryptoAuditManager:
    def __init__(self):
        self.connection = MySQLConnectionProvider.get_instance().get_connection()
        self.cursor = self.connection.cursor(MySQLdb.cursors.DictCursor)

    def complete(self):
        try:
            self.cursor.close()
        finally:
            self.connection.close()

    def log_audit(self, audit: CryptoAudit) -> int:
        insert_sql = f"""
            INSERT INTO {MySQLTable.NVFLARE_JOB_CRYPTO_AUDIT}
            (
                nvflare_job_id,
                security_level,
                ring_dimension,
                batch_size,
                scale_mod_size,
                multiplicative_depth,
                scaling_technique,
                keyswitch_technique,
                ckks_data_type,
                ind_cpa_noise_bits
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """

        params = (
            audit.nvflare_job_id,
            audit.security_level,
            audit.ring_dimension,
            audit.batch_size,
            audit.scale_mod_size,
            audit.multiplicative_depth,
            audit.scaling_technique,
            audit.keyswitch_technique,
            audit.ckks_data_type,
            audit.ind_cpa_noise_bits,
        )

        self.cursor.execute(insert_sql, params)
        self.connection.commit()
        return self.cursor.lastrowid
