import os
import random

import pymysql
from typing import Optional


MYSQL_HOST = os.getenv("MYSQL_HOST", "localhost")
MYSQL_PORT = int(os.getenv("MYSQL_PORT", "3306"))
MYSQL_USER = os.getenv("MYSQL_USER", "root")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "")
MYSQL_DB = os.getenv("MYSQL_DB", "graph_benchmark")


def get_mysql_connection(db: Optional[str] = None):
    return pymysql.connect(
        host=MYSQL_HOST,
        port=MYSQL_PORT,
        user=MYSQL_USER,
        password=MYSQL_PASSWORD,
        database=db,
        autocommit=True,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.Cursor,
    )


def load_friends_graph(person_count: int = 10_000, avg_degree: int = 20) -> None:
    """
    在 MySQL 中构造等价的“高分支度社交图”：

    - persons(id BIGINT PRIMARY KEY)
    - friendships(person_id BIGINT, friend_id BIGINT, KEY (person_id), KEY (friend_id))
    """
    # 创建数据库
    with get_mysql_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"CREATE DATABASE IF NOT EXISTS {MYSQL_DB} "
            "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
        )

    # 创建表并插入数据
    with get_mysql_connection(MYSQL_DB) as conn, conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS persons (
              id BIGINT PRIMARY KEY
            ) ENGINE=InnoDB
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS friendships (
              person_id BIGINT NOT NULL,
              friend_id BIGINT NOT NULL,
              KEY idx_person (person_id),
              KEY idx_friend (friend_id)
            ) ENGINE=InnoDB
            """
        )

        cur.execute("TRUNCATE TABLE friendships")
        cur.execute("TRUNCATE TABLE persons")

        # persons
        cur.executemany(
            "INSERT INTO persons (id) VALUES (%s)",
            [(i,) for i in range(person_count)],
        )

        # friendships（无向，用两条有向边表示）
        rows = []
        for pid in range(person_count):
            for _ in range(avg_degree):
                qid = random.randint(0, person_count - 1)
                if qid == pid:
                    continue
                rows.append((pid, qid))
                rows.append((qid, pid))

        batch_size = 10_000
        for offset in range(0, len(rows), batch_size):
            batch = rows[offset : offset + batch_size]
            cur.executemany(
                "INSERT INTO friendships (person_id, friend_id) VALUES (%s, %s)",
                batch,
            )


def main() -> None:
    person_count = int(os.getenv("FRIEND_PERSON_COUNT", "10000"))
    avg_degree = int(os.getenv("FRIEND_AVG_DEGREE", "20"))
    print(f"Preparing MySQL friends graph: persons={person_count}, avg_degree={avg_degree} in database '{MYSQL_DB}' ...")
    load_friends_graph(person_count=person_count, avg_degree=avg_degree)
    print("Done.")


if __name__ == "__main__":
    main()

