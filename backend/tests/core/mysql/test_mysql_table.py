from app.core.mysql.MySQLTable import MySQLTable


def test_mysql_table_stringifies_to_table_name():
    assert str(MySQLTable.NVFLARE_JOBS) == "nvflare_jobs"
    assert f"{MySQLTable.USERS}" == "users"
