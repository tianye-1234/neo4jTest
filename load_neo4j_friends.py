import os
import random

from neo4j import GraphDatabase


URI = os.getenv("NEO4J_URI", "neo4j://localhost:7687")
USER = os.getenv("NEO4J_USER", "neo4j")
PASSWORD = os.getenv("NEO4J_PASSWORD", "test")


def load_friends_graph(driver, person_count: int = 10_000, avg_degree: int = 20) -> None:
    """
    在 Neo4j 中构造“高分支度社交图”：

    - 创建 person_count 个 :Person 节点（id 0..person_count-1）
    - 为每个节点随机创建 avg_degree 个无向好友关系（用两条有向 :FRIEND 表示）
    """
    with driver.session() as session:
        # 清理旧的 Person / FRIEND 数据，避免干扰
        session.run("MATCH (p:Person) DETACH DELETE p")

        # 创建 Person 节点
        session.run(
            """
            UNWIND range(0, $person_count - 1) AS i
            CREATE (:Person {id: i})
            """,
            person_count=person_count,
        )

        # 批量创建 FRIEND 关系
        batch_size = 1000
        for offset in range(0, person_count, batch_size):
            upper = min(person_count, offset + batch_size)
            ids = list(range(offset, upper))
            pairs = []
            for pid in ids:
                # 简单的伪随机邻居（保证 id 落在范围内）
                for _ in range(avg_degree):
                    qid = random.randint(0, person_count - 1)
                    if qid == pid:
                        continue
                    pairs.append((pid, qid))

            if not pairs:
                continue

            session.run(
                """
                UNWIND $pairs AS pair
                MATCH (a:Person {id: pair[0]}), (b:Person {id: pair[1]})
                MERGE (a)-[:FRIEND]->(b)
                MERGE (b)-[:FRIEND]->(a)
                """,
                pairs=pairs,
            )


def main() -> None:
    person_count = int(os.getenv("FRIEND_PERSON_COUNT", "10000"))
    avg_degree = int(os.getenv("FRIEND_AVG_DEGREE", "20"))
    driver = GraphDatabase.driver(URI, auth=(USER, PASSWORD))
    try:
        print(f"Preparing Neo4j friends graph: persons={person_count}, avg_degree={avg_degree} ...")
        load_friends_graph(driver, person_count=person_count, avg_degree=avg_degree)
        print("Done.")
    finally:
        driver.close()


if __name__ == "__main__":
    main()

