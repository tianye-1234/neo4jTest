### Neo4j 底层存储是不是“链表”？

**不是用 Java 的 `LinkedList` 这种高级容器，但关系和属性在磁盘上确实是用“记录 + 指针链（链表思想）”来组织的。**

更精确一点：

- 节点、关系、属性在磁盘上都是**固定大小的 record（记录）文件**，分别存放在：
  - `neostore.nodestore.db`：节点记录
  - `neostore.relationshipstore.db`：关系记录
  - `neostore.propertystore.db`：属性记录
- 每条记录都有自己的 **ID**，通过 `ID * recordSize` 可以直接算出其在文件中的偏移。
- **关系记录里包含“前一条 / 后一条关系 ID”指针**（对起点和终点各有一对），再加上起点节点 ID、终点节点 ID、关系类型 ID、首个属性记录 ID 等。
- 每个节点记录中只需要保存“自己关系链的起始关系 ID”，从这条关系开始，沿着 prev/next ID 指针就能遍历出该节点的全部关系。
- 属性记录本身也形成一个**属性 record 的单向链表**：每条属性记录保存一个或数个属性块，并且有 “next property record ID” 指针。

从**磁盘结构**角度看，Neo4j 早期/经典存储引擎确实是用“记录 + ID 指针链”来组织图的（节点挂一条关系链，关系之间互相有 prev/next），和我们说的“链表”思想是一致的，只是实现是自定义的二进制 record，而不是内存容器。

在较新版本中还出现了 `aligned` / `block` 等存储格式，用更多内联和数据对齐优化了“指针追踪”的成本，但底层仍然基于节点/关系/属性记录和 ID 引用。

---

### 关键结构：NodeRecord / RelationshipRecord / PropertyRecord

以下路径基于 Neo4j 开源仓库（`neo4j/neo4j`）的典型版本（3.x/4.x），5.x 虽有演进但核心概念相同。

#### 1. 关系记录（关系链表的核心）

- **类**：`RelationshipRecord`
- 示例路径（3.5 分支）：
  - `community/kernel/src/main/java/org/neo4j/kernel/impl/store/record/RelationshipRecord.java`
- 典型字段（简化概念）：
  - `long firstNode;` / `long secondNode;`  
    起点 / 终点节点 ID。
  - `long firstPrevRel;` / `long firstNextRel;`  
    以 `firstNode` 为端点时，前一条/后一条关系的 ID。
  - `long secondPrevRel;` / `long secondNextRel;`  
    以 `secondNode` 为端点时，前一条/后一条关系的 ID。
  - `long nextProp;`  
    属性链起点记录 ID。

**含义：**

- 对于某个节点 `n`，它的 `NodeRecord.nextRel` 给出“挂在这个节点上的关系链起点 ID”。
- 从这条 `RelationshipRecord` 开始，通过 `firstNextRel` / `secondNextRel`（取决于这条关系是该节点的 firstNode 还是 secondNode），可以沿着链表访问这个节点的所有关系。
- 关系记录本身同时挂在起点和终点的链上，形成“以节点为头的双向链表结构”。

#### 2. 节点记录（关系链的入口）

- **类**：`NodeRecord`
- 示例路径（1.9 分支，较老版本，但结构示意清楚）：
  - `community/kernel/src/main/java/org/neo4j/kernel/impl/nioneo/store/NodeRecord.java`
- 典型字段：
  - `long nextRel;`  
    这个节点的一条关系链起点（关系 ID）。
  - `long nextProp;`  
    属性链起点。

**含义：**

- 遍历一个节点的所有关系：
  1. 从节点记录的 `nextRel` 拿到第一条 `RelationshipRecord`；
  2. 看这条关系里，当前节点是 `firstNode` 还是 `secondNode`；
  3. 根据位置选择 `firstNextRel` 或 `secondNextRel` 继续往后走，直到到达链表末尾。

这就是 Neo4j 所谓的“指针式关系链”——不需要做“全表扫描 + 过滤 node_id”，而是从节点出发顺着链走。

#### 3. 属性记录（属性链）

- **类**：`PropertyRecord`、`PropertyBlock` 等
- 路径类似：
  - `.../org/neo4j/kernel/impl/store/record/PropertyRecord.java`
- 典型字段：
  - `long nextProp;`  
    下一条属性记录 ID。

节点或关系的 `nextProp` 指向第一条 `PropertyRecord`，然后通过 `nextProp` 一条条往下追；每条属性记录内部用 `PropertyBlock` 保存具体 key/value，通过指向 key/value 目录（property key store）来管理属性名和值。

---

### 文件层 & 存储引擎代码大致在哪里？

除了 record 类本身，还可以从以下目录看到完整的“记录 <-> 文件”实现：

- **记录存取类**（负责对 `*.db` 文件进行读写）：
  - 包路径大致是：
    - `org.neo4j.kernel.impl.store`
  - 重要类：
    - `NodeStore`（节点存取）
    - `RelationshipStore`（关系存取）
    - `PropertyStore`（属性存取）
  - 它们负责：
    - 用 record ID 计算文件偏移；
    - 把 Java 层的 `NodeRecord` / `RelationshipRecord` / `PropertyRecord` 编码/解码成二进制；
    - 管理空闲记录池、记录版本等。

- **磁盘文件格式概览文档**：
  - 官方文档：
    - `Store formats - Neo4j Operations Manual`
  - 知识库文章：
    - `Understanding Neo4j’s data on disk`
  - 社区博客：
    - Max De Marzi 的《Neo4j Internals》

在这些文档和类中，你可以看到类似描述：

- `neostore.relationshipstore.db`：每条关系记录占 34 字节（早期格式），包含节点 ID、关系类型 ID、prev/next 关系指针等；
- `neostore.nodestore.db`：每条节点记录占 15 字节，包含 `nextRel`、`nextProp` 等；
- `neostore.propertystore.db`：每条属性记录占 41 字节，包含下一条属性记录 ID 等。

---

### 与当前实验的联系

在你的这个项目里，我们把 MySQL 的链表 / 好友图原样镜像到了 Neo4j：

- 链表场景：
  - MySQL 的 `nodes(id, chain_id, next_id)` ↔ Neo4j 的 `(:Node {id, chain_id})-[:NEXT]->(:Node)`；
  - 这些 `Node` / `NEXT` 在磁盘上就是一堆 `NodeRecord` / `RelationshipRecord` + ID 链表。

- 好友图场景：
  - MySQL 的 `persons(id)`、`friendships(person_id, friend_id)` ↔ Neo4j 的 `(:Person {id})-[:FRIEND]->(:Person {id})`；
  - Neo4j 遍历 `FRIEND` 的时候，底层就是从 `NodeRecord.nextRel` 出发，沿着 `RelationshipRecord` 中 prev/next 指针链遍历所有好友。

所以回答总结为：

- **概念上**：Neo4j 确实用“链式结构”组织关系和属性，只不过是在自定义的记录格式和 ID 指针层面实现的，而不是语言层面的 `LinkedList`；
- **代码位置**：可以重点看：
  - `org.neo4j.kernel.impl.store.record.RelationshipRecord`
  - `org.neo4j.kernel.impl.store.record.NodeRecord`
  - `org.neo4j.kernel.impl.store.record.PropertyRecord`
  - 以及同目录下的 `NodeStore` / `RelationshipStore` / `PropertyStore`。

