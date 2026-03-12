import os
import random
import time
from typing import Optional, Tuple

import pymysql
from neo4j import GraphDatabase


# Neo4j 配置
URI = os.getenv("NEO4J_URI", "neo4j://localhost:7687")
USER = os.getenv("NEO4J_USER", "neo4j")
PASSWORD = os.getenv("NEO4J_PASSWORD", "test")


def get_driver():
    return GraphDatabase.driver(URI, auth=(USER, PASSWORD))


def benchmark_traversal(driver, start_id: int, depth: int, runs: int = 50) -> Tuple[float, int]:
    """
    从给定起点出发，沿着 :NEXT 关系做固定深度的遍历，多次重复并统计耗时。
    返回 (平均耗时毫秒, 每次遍历访问到的节点数)。
    """
    # 使用纯 Cypher 的可变长度路径，而不是依赖 APOC。
    # 由于变量深度参数不能直接用于 *1..$depth 语法，这里在 Python 侧内联深度。
    cypher = f"""
    MATCH p = (n:Node {{id: $start_id}})-[:NEXT*1..{depth}]->(m:Node)
    WHERE length(p) = {depth}
    RETURN length(p) AS hops
    """

    with driver.session() as session:
        durations = []
        last_hops = 0
        for _ in range(runs):
            t0 = time.perf_counter()
            result = session.run(cypher, start_id=start_id, depth=depth)
            record = result.single()
            t1 = time.perf_counter()
            durations.append((t1 - t0) * 1000)
            last_hops = record["hops"] if record else 0

    avg_ms = sum(durations) / len(durations)
    return avg_ms, last_hops


########################
# MySQL 等价链表建模与基准
########################

MYSQL_HOST = os.getenv("MYSQL_HOST", "localhost")
MYSQL_PORT = int(os.getenv("MYSQL_PORT", "3306"))
MYSQL_USER = os.getenv("MYSQL_USER", "root")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "")
MYSQL_DB = os.getenv("MYSQL_DB", "graph_benchmark")


def get_mysql_connection(db: Optional[str] = None):
    """
    获取 MySQL 连接。
    如果 db 为 None，则连接到默认系统库，用于创建数据库。
    """
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


def benchmark_mysql_traversal(depth: int = 5, runs: int = 500) -> float:
    """
    在 MySQL 中做等价的“从随机起点沿链表走固定深度”的查询基准。
    查询形式为 5 次自连接：

      n0 JOIN n1 JOIN n2 JOIN n3 JOIN n4 JOIN n5

    返回：每次查询的平均耗时（毫秒）。
    """
    sql = """
    SELECT n5.id
    FROM nodes AS n0
    JOIN nodes AS n1 ON n1.id = n0.next_id
    JOIN nodes AS n2 ON n2.id = n1.next_id
    JOIN nodes AS n3 ON n3.id = n2.next_id
    JOIN nodes AS n4 ON n4.id = n3.next_id
    JOIN nodes AS n5 ON n5.id = n4.next_id
    WHERE n0.id = %s
    """

    with get_mysql_connection(MYSQL_DB) as conn, conn.cursor() as cur:
        durations: list[float] = []
        max_start = 40_000  # 5 万节点时留出足够空间保证能走完 5 跳
        for _ in range(runs):
            start_id = random.randint(0, max_start)
            t0 = time.perf_counter()
            cur.execute(sql, (start_id,))
            cur.fetchall()
            t1 = time.perf_counter()
            durations.append((t1 - t0) * 1000)

    avg_ms = sum(durations) / len(durations)
    return avg_ms


def run_benchmarks() -> None:
    depth = 5
    neo_runs = 1
    mysql_runs = 1

    print("=== Neo4j: 深度遍历基准（假设数据已由 load_neo4j_data.py 准备） ===")
    driver = get_driver()
    try:
        neo_avg_ms, hops = benchmark_traversal(driver, start_id=0, depth=depth, runs=neo_runs)
        print(f"[Neo4j] depth={depth}, runs={neo_runs}, avg={neo_avg_ms:.3f} ms, hops={hops}")
    finally:
        driver.close()

    print("=== MySQL: 深度遍历基准（多次 5 层自连接，假设数据已由 load_mysql_data.py 准备） ===")
    mysql_avg_ms = benchmark_mysql_traversal(depth=depth, runs=mysql_runs)
    print(f"[MySQL] depth={depth}, runs={mysql_runs}, avg={mysql_avg_ms:.3f} ms")


if __name__ == "__main__":
    run_benchmarks()
