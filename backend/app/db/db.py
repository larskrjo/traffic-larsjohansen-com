import os
from typing import Any, cast

from mysql.connector import pooling

from app.constants.secrets import SECRETS


def get_dev_secret():
    return {"host": "localhost", "port": "3306", "user": "root", "password": "Abcd1234"}


def get_prod_secret():
    return {
        "host": "mysql",
        "port": "3306",
        "user": SECRETS["mysql_user"],
        "password": SECRETS["mysql_password"],
    }


dbconfig = {"database": "traffic_larsjohansen_com", "autocommit": True}

if os.getenv("DEVELOPMENT_MODE") == "prod":
    dbconfig = dbconfig | get_prod_secret()
else:
    dbconfig = dbconfig | get_dev_secret()

pool = pooling.MySQLConnectionPool(
    pool_name="traffic-bay-area",
    pool_size=5,
    **cast(dict[str, Any], dbconfig),
)


class Database:
    def __init__(self):
        self.conn = None
        self.cursor = None

    def __enter__(self):
        self.conn = pool.get_connection()
        self.cursor = self.conn.cursor()
        self.cursor.execute("SET time_zone = '+00:00'")
        return self.cursor

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.conn is not None:
            if exc_type:
                self.conn.rollback()
            else:
                self.conn.commit()
        if self.cursor is not None:
            self.cursor.close()
        if self.conn is not None:
            self.conn.close()
