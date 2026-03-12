import os
import random
import time
from typing import Optional

import pymysql
from neo4j import GraphDatabase


# Neo4j config
NEO4J_URI = os.getenv("NEO4J_URI", "neo4j://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "test")


def get_neo4j_driver():
    return GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))


# MySQL config
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


def build_neo4j_cypher(hops: int) -> str:
    """
    根据 hops(2/3/4) 动态生成朋友多跳推荐的 Cypher。
    """
    asserts = []
    path = "(u:Person {id: $user_id})"
    last_var = "u"
    for i in range(1, hops + 1):
        var = f"f{i}"
        path += f"-[:FRIEND]->({var}:Person)"
        last_var = var
    # 排除自己和已是直接好友
    asserts.append(f"NOT (u)-[:FRIEND]->({last_var})")
    asserts.append(f"{last_var} <> u")
    where_clause = " AND ".join(asserts)
    cypher = f"""
    MATCH {path}
    WHERE {where_clause}
    RETURN DISTINCT {last_var}.id AS fof_id
    """
    return cypher


def benchmark_neo4j_friend_recommendations(user_id: int, hops: int, runs: int = 20) -> float:
    """
    在 Neo4j 中做 N 跳朋友推荐（N=2/3/4），排除自己和已是好友。
    """
    cypher = build_neo4j_cypher(hops)

    driver = get_neo4j_driver()
    try:
        with driver.session() as session:
            durations: list[float] = []
            for _ in range(runs):
                t0 = time.perf_counter()
                result = session.run(cypher, user_id=user_id)
                _ = [r["fof_id"] for r in result]
                t1 = time.perf_counter()
                durations.append((t1 - t0) * 1000)
    finally:
        driver.close()

    return sum(durations) / len(durations)


def build_mysql_sql(hops: int) -> str:
    """
    根据 hops(2/3/4) 动态生成等价的 MySQL SQL。
    friendships(person_id, friend_id) 存储有向好友关系。
    """
    # f1 始终是一跳：f1.person_id = user
    join_parts = []
    # 第二跳及以后
    for i in range(2, hops + 1):
        prev = "f1" if i == 2 else f"f{i-1}"
        curr = f"f{i}"
        join_parts.append(f"JOIN friendships AS {curr} ON {curr}.person_id = {prev}.friend_id")
    joins = "\n    ".join(join_parts)
    last_alias = f"f{hops}"

    sql = f"""
    SELECT DISTINCT {last_alias}.friend_id AS fof_id
    FROM friendships AS f1
    {joins}
    LEFT JOIN friendships AS already
      ON already.person_id = f1.person_id
     AND already.friend_id = {last_alias}.friend_id
    WHERE f1.person_id = %s
      AND {last_alias}.friend_id <> f1.person_id
      AND already.friend_id IS NULL
    """
    return sql


def benchmark_mysql_friend_recommendations(user_id: int, hops: int, runs: int = 20) -> float:
    """
    在 MySQL 中做等价的 N 跳朋友推荐（N=2/3/4）。
    """
    sql = build_mysql_sql(hops)

    with get_mysql_connection(MYSQL_DB) as conn, conn.cursor() as cur:
        durations: list[float] = []
        for _ in range(runs):
            t0 = time.perf_counter()
            cur.execute(sql, (user_id,))
            _ = cur.fetchall()
            t1 = time.perf_counter()
            durations.append((t1 - t0) * 1000)

    return sum(durations) / len(durations)


def main() -> None:
    # 随机选一个用户做推荐测试
    person_count = int(os.getenv("FRIEND_PERSON_COUNT", "10000"))
    user_id = random.randint(0, person_count - 1)
    runs = int(os.getenv("FRIEND_BENCHMARK_RUNS", "50"))

    print(f"Friend recommendation benchmark for user_id={user_id}, runs={runs}")

    for hops in (2, 3, 4):
        print(f"\n=== {hops} hops ===")
        neo4j_avg = benchmark_neo4j_friend_recommendations(user_id=user_id, hops=hops, runs=runs)
        print(f"[Neo4j]  hops={hops}, avg={neo4j_avg:.3f} ms over {runs} runs")

        mysql_avg = benchmark_mysql_friend_recommendations(user_id=user_id, hops=hops, runs=runs)
        print(f"[MySQL] hops={hops}, avg={mysql_avg:.3f} ms over {runs} runs")


if __name__ == "__main__":
    main()

