### 项目简介

这个仓库用于对比 **Neo4j** 和 **MySQL** 在不同「关系查询」场景下的性能表现，包括：

- 长链表型数据的深度遍历基准（`neo_benchmark.py`）
- 社交网络“朋友的朋友（的朋友）推荐”基准（`friends_benchmark.py`）
- 构造等价数据的脚本（Neo4j / MySQL 各一份）
- 简单的 Neo4j 连通性测试（`pytest`）

---

### 环境准备

- Python 3.9+（推荐）
- 已安装并可连接的：
  - Neo4j（默认地址 `neo4j://localhost:7687`）
  - MySQL（默认地址 `localhost:3306`）

#### 1. 创建虚拟环境并安装依赖

```bash
cd /Users/tianye/code/neo4jTest
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

---

### 使用 `.env` 管理环境变量

项目根目录已经提供了一个示例 `.env` 文件，包含 Neo4j / MySQL 以及节点数量等配置：

```env
NEO4J_URI=neo4j://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=test

MYSQL_HOST=localhost
MYSQL_PORT=3306
MYSQL_USER=root
MYSQL_PASSWORD=
MYSQL_DB=graph_benchmark

NODE_COUNT=50000
```

你可以根据自己本地环境修改 `.env`，然后在运行脚本前让 shell 自动加载这些变量，例如：

```bash
cd /Users/tianye/code/neo4jTest
set -a           # 让当前 shell 自动导出变量
source .env      # 加载 .env 中的配置
set +a
```

之后再执行下面的各类脚本（插数、基准测试等），就会自动读取这些环境变量。

---

### 数据模型说明

详见 `neo4j_mysql_benchmark.md`，这里只简单回顾：

- 逻辑结构是一条长链表：

0 \rightarrow 1 \rightarrow 2 \rightarrow \dots \rightarrow (N-1)

- Neo4j：
  - 节点：`(:Node {id, chain_id})`
  - 关系：`(a:Node)-[:NEXT]->(b:Node)`
- MySQL：
  - 表：`nodes(id BIGINT PRIMARY KEY, chain_id BIGINT, next_id BIGINT)`
  - 行：`(id=i, chain_id=0, next_id=i+1)`，尾节点 `next_id=NULL`。

---

### 一、长链表场景：向 Neo4j 插入测试数据

脚本：`load_neo4j_data.py`

**功能**：在 Neo4j 中创建一条长度为 `NODE_COUNT` 的单链，并清空原有数据。

- 默认配置（可通过环境变量覆盖）：
  - `NEO4J_URI`：默认 `neo4j://localhost:7687`
  - `NEO4J_USER`：默认 `neo4j`
  - `NEO4J_PASSWORD`：默认 `test`
  - `NODE_COUNT`：默认 `50000`（5 万节点，可在 `.env` 中修改）

**执行方法**：

```bash
cd /Users/tianye/code/neo4jTest
source .venv/bin/activate

# 如需修改节点数量，比如 100 万：
# export NODE_COUNT=1000000

python load_neo4j_data.py
```

执行完成后，Neo4j 中将存在：

```text
(:Node {id: 0, chain_id: 0})-[:NEXT]->(:Node {id: 1, chain_id: 0})->...->(:Node {id: NODE_COUNT-1, chain_id: 0})
```

---

### 二、长链表场景：向 MySQL 插入测试数据

脚本：`load_mysql_data.py`

**功能**：在 MySQL 中创建数据库和表，并插入等价的链式数据：

- 数据库：`graph_benchmark`（可通过 `MYSQL_DB` 环境变量修改）
- 表结构：`nodes(id BIGINT PRIMARY KEY, chain_id BIGINT, next_id BIGINT)`
- 数据：一条长度为 `NODE_COUNT` 的单链。

默认配置（可通过环境变量覆盖）：

- `MYSQL_HOST`：默认 `localhost`
- `MYSQL_PORT`：默认 `3306`
- `MYSQL_USER`：默认 `root`
- `MYSQL_PASSWORD`：默认空
- `MYSQL_DB`：默认 `graph_benchmark`
- `NODE_COUNT`：默认 `50000`

**执行方法**：

```bash
cd /Users/tianye/code/neo4jTest
source .venv/bin/activate

# 根据你本地 MySQL 情况设置环境变量（示例）：
# export MYSQL_HOST=localhost
# export MYSQL_PORT=3306
# export MYSQL_USER=root
# export MYSQL_PASSWORD=your_password
# export MYSQL_DB=graph_benchmark
# export NODE_COUNT=500000

python load_mysql_data.py
```

执行完成后，MySQL 中将有：

```text
nodes 表：
  id:       0..NODE_COUNT-1
  chain_id: 全部为 0
  next_id:  i < NODE_COUNT-1 时为 i+1，尾节点为 NULL
```

---

### 三、长链表场景：Neo4j / MySQL 深度遍历基准（`neo_benchmark.py`）

**功能**：

- 假设你已经用 `load_neo4j_data.py` / `load_mysql_data.py` 构造好同样的链式数据；
- 对比“从起点沿链表走 5 步”的查询性能：
  - Neo4j：使用可变长度路径匹配 `MATCH p=(n)-[:NEXT*1..5]->(m)`，限制 `length(p)=5`；
  - MySQL：在 `nodes` 表上做 5 层自连接。

**执行方法**：

```bash
cd /Users/tianye/code/neo4jTest
source .venv/bin/activate
set -a
source .env
set +a

# 确保已经插入链表数据
python load_neo4j_data.py
python load_mysql_data.py

# 只做查询基准
python neo_benchmark.py
```

在一组典型配置下（5 万节点、depth=5、runs=1），在你的环境中观测到的一个样例结果为：

```text
[Neo4j] depth=5, runs=1, avg≈31 ms, hops=5
[MySQL] depth=5, runs=1, avg≈0.3 ms
```

说明在“严格单链表 + 主键等值自连接”的场景下，MySQL 更擅长这种访问模式。

---

### 四、社交图场景：构造“好友图”数据

这一组脚本用来构造**高分支度社交网络**，用来测试“朋友的朋友（的朋友）推荐”这类更偏图算法的查询。

#### 1. 向 Neo4j 插入好友图数据（`load_neo4j_friends.py`）

- 模型：
  - 节点：`(:Person {id})`
  - 关系：`(:Person)-[:FRIEND]-(:Person)`（内部用两条有向边）
- 主要参数（可通过环境变量覆盖）：
  - `FRIEND_PERSON_COUNT`：用户数量，默认 `10000`
  - `FRIEND_AVG_DEGREE`：平均好友数，默认 `20`

执行示例（与当前实验配置一致的较小规模）：

```bash
cd /Users/tianye/code/neo4jTest
source .venv/bin/activate
set -a
source .env
export FRIEND_PERSON_COUNT=2000 FRIEND_AVG_DEGREE=15
set +a

python load_neo4j_friends.py
```

#### 2. 向 MySQL 插入好友图数据（`load_mysql_friends.py`）

- 模型：
  - 表 `persons(id BIGINT PRIMARY KEY)`
  - 表 `friendships(person_id BIGINT, friend_id BIGINT, KEY idx_person, KEY idx_friend)`
- 参数同上：
  - `FRIEND_PERSON_COUNT`、`FRIEND_AVG_DEGREE`

执行示例：

```bash
cd /Users/tianye/code/neo4jTest
source .venv/bin/activate
set -a
source .env
export FRIEND_PERSON_COUNT=2000 FRIEND_AVG_DEGREE=15
set +a

python load_mysql_friends.py
```

---

### 五、社交图场景：“三跳朋友推荐”基准（`friends_benchmark.py`）

> 说明：为了保证试验公平，本项目采用 **MySQL 生成源数据**，再由 `load_neo4j_friends.py` **从 MySQL 镜像到 Neo4j**。
> 因此两边数据完全一致，benchmark 也会从同一个固定起点 `user_id` 开始查询（默认 `0`）。

**查询问题：**

- 给定某个用户 `u`，查找“朋友的朋友的朋友”（三跳）作为候选推荐；
- 排除：
  - 已经是 `u` 的直接好友；
  - `u` 本人；
- 对结果去重。

**Neo4j 查询：**

```cypher
MATCH (u:Person {id: $user_id})-[:FRIEND]->(f1:Person)
      -[:FRIEND]->(f2:Person)
      -[:FRIEND]->(f3:Person)
WHERE NOT (u)-[:FRIEND]->(f3) AND f3 <> u
RETURN DISTINCT f3.id AS fof_id;
```

**MySQL 等价查询：**

```sql
SELECT DISTINCT f3.friend_id AS fof_id
FROM friendships AS f1
JOIN friendships AS f2 ON f2.person_id = f1.friend_id
JOIN friendships AS f3 ON f3.person_id = f2.friend_id
LEFT JOIN friendships AS already
  ON already.person_id = f1.person_id
 AND already.friend_id = f3.friend_id
WHERE f1.person_id = ?
  AND f3.friend_id <> f1.person_id
  AND already.friend_id IS NULL;
```

**执行方法：**

```bash
cd /Users/tianye/code/neo4jTest
source .venv/bin/activate
set -a
source .env
export FRIEND_PERSON_COUNT=2000 FRIEND_AVG_DEGREE=15 FRIEND_BENCHMARK_RUNS=5
set +a

# 一条命令：带 --load 时会自动重建数据并镜像到 Neo4j
python friends_benchmark.py --load
```

也可以只跑 benchmark（假设你之前已经执行过 `--load` 或者已经手动跑过 `load_*` 脚本）：

```bash
python friends_benchmark.py --runs 5 --user-id 0 --hops 2,3,4
```

常用参数：

- **`--load`**：自动执行 `load_mysql_friends.py -> load_neo4j_friends.py`，保证两端数据一致且干净
- **`--person-count`**：用户数量（也可用环境变量 `FRIEND_PERSON_COUNT`）
- **`--avg-degree`**：平均好友数（也可用环境变量 `FRIEND_AVG_DEGREE`）
- **`--runs`**：每个 hops 的重复次数（也可用环境变量 `FRIEND_BENCHMARK_RUNS`）
- **`--user-id`**：固定起点（也可用环境变量 `FRIEND_USER_ID`），默认 `0`
- **`--random-user`**：随机选择起点（不利于复现）
- **`--hops`**：逗号分隔的跳数列表（2/3/4），也可用 `FRIEND_HOPS`

在上述配置下，你当前环境的一次实际跑数结果为：

```text
Friend-of-friend benchmark for user_id=25, runs=50
[Neo4j]  avg≈89.6 ms over 50 runs
[MySQL] avg≈733.8 ms over 50 runs
```

可以看到，在这种**高分支度 + 多跳 + 去重 + 排除模式匹配**的典型“图查询”场景中，Neo4j 明显快于 MySQL。

---

### 六、Neo4j 连通性测试（可选）

使用 `pytest` 对 Neo4j 做最基本的连通性和读写校验：

```bash
cd /Users/tianye/code/neo4jTest
source .venv/bin/activate
pytest -q
```

要求 Neo4j 服务已启动，且账号密码与环境变量一致。