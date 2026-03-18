import argparse
import os
import random
import subprocess
import sys
import time
from typing import Optional, Sequence

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


def run_step(cmd: Sequence[str], env: dict[str, str]) -> None:
    subprocess.run(cmd, check=True, env=env)


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


def parse_hops(value: str) -> list[int]:
    parts = [p.strip() for p in value.split(",") if p.strip()]
    hops = [int(p) for p in parts]
    allowed = {2, 3, 4}
    bad = [h for h in hops if h not in allowed]
    if bad:
        raise argparse.ArgumentTypeError(f"--hops 只支持 2,3,4，收到: {bad}")
    if not hops:
        raise argparse.ArgumentTypeError("--hops 不能为空")
    return hops


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Neo4j vs MySQL 多跳好友推荐基准（同一数据源镜像，公平对比）"
    )
    parser.add_argument(
        "--load",
        action="store_true",
        help="运行前自动执行数据加载：load_mysql_friends.py -> load_neo4j_friends.py",
    )
    parser.add_argument(
        "--person-count",
        type=int,
        default=int(os.getenv("FRIEND_PERSON_COUNT", "10000")),
        help="用户数量（默认读 FRIEND_PERSON_COUNT）",
    )
    parser.add_argument(
        "--avg-degree",
        type=int,
        default=int(os.getenv("FRIEND_AVG_DEGREE", "20")),
        help="平均好友数（默认读 FRIEND_AVG_DEGREE）",
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=int(os.getenv("FRIEND_BENCHMARK_RUNS", "5")),
        help="每种 hops 重复运行次数（默认读 FRIEND_BENCHMARK_RUNS）",
    )
    parser.add_argument(
        "--user-id",
        type=int,
        default=int(os.getenv("FRIEND_USER_ID", "0")),
        help="固定起点 user_id（默认 0，保证每次同一起点更公平；也可用 FRIEND_USER_ID）",
    )
    parser.add_argument(
        "--random-user",
        action="store_true",
        help="忽略 --user-id，随机选择一个 user_id（不建议用于对比复现）",
    )
    parser.add_argument(
        "--hops",
        type=parse_hops,
        default=parse_hops(os.getenv("FRIEND_HOPS", "2,3,4")),
        help="要测试的跳数列表，逗号分隔，例如 2,3,4（默认读 FRIEND_HOPS）",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=int(os.getenv("FRIEND_SEED", "42")),
        help="随机种子（仅影响 --random-user 选择，默认 42；也可用 FRIEND_SEED）",
    )

    args = parser.parse_args()

    if args.person_count <= 1:
        raise SystemExit("--person-count 必须 > 1")
    if args.avg_degree <= 0:
        raise SystemExit("--avg-degree 必须 > 0")
    if args.runs <= 0:
        raise SystemExit("--runs 必须 > 0")

    env = os.environ.copy()
    env["FRIEND_PERSON_COUNT"] = str(args.person_count)
    env["FRIEND_AVG_DEGREE"] = str(args.avg_degree)
    env["FRIEND_BENCHMARK_RUNS"] = str(args.runs)
    env["FRIEND_HOPS"] = ",".join(str(h) for h in args.hops)
    env["FRIEND_SEED"] = str(args.seed)

    if args.load:
        print("== Loading data (MySQL -> Neo4j mirror) ==")
        run_step([sys.executable, "load_mysql_friends.py"], env=env)
        run_step([sys.executable, "load_neo4j_friends.py"], env=env)

    if args.random_user:
        random.seed(args.seed)
        user_id = random.randint(0, args.person_count - 1)
    else:
        user_id = args.user_id
        if not (0 <= user_id < args.person_count):
            raise SystemExit(f"--user-id 必须在 [0, {args.person_count - 1}] 内")

    print(
        "Friend recommendation benchmark "
        f"for user_id={user_id}, runs={args.runs}, persons={args.person_count}, avg_degree={args.avg_degree}"
    )

    for hops in args.hops:
        print(f"\n=== {hops} hops ===")
        neo4j_avg = benchmark_neo4j_friend_recommendations(user_id=user_id, hops=hops, runs=args.runs)
        print(f"[Neo4j]  hops={hops}, avg={neo4j_avg:.3f} ms over {args.runs} runs")

        mysql_avg = benchmark_mysql_friend_recommendations(user_id=user_id, hops=hops, runs=args.runs)
        print(f"[MySQL] hops={hops}, avg={mysql_avg:.3f} ms over {args.runs} runs")


if __name__ == "__main__":
    main()

