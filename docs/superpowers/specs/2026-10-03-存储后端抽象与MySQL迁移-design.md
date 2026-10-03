# 存储后端抽象与 MySQL 迁移设计（阶段 54）

- 日期：2026-10-03
- 状态：待用户评审
- 选型：路径 1（四步渐进）+ 本地 Docker MySQL 实例
- 相关前置：阶段 53（用户视角优化）已收尾

---

## 1. 背景与问题

目标场景：**对外服务，几十到几百并发用户**。当前后端全部数据存 SQLite（`data/daa.db`，实测 102.77 MB）。

### 1.1 真瓶颈：把 DataFrame 存进数据库列

实测各表空间占用：

| 表 | 行数 | 平均行体积 | 估算占用 |
|---|---|---|---|
| datasets | 145 | **380.9 KB** | **53.93 MB** |
| reports | 84 | 21.9 KB | 1.80 MB |
| 其他业务表（users/audit_log/email_codes/...） | ~300 | <0.3 KB | <0.05 MB |

`datasets.df_json` 列用 `df.to_json(orient="records")` 把整个 DataFrame 序列化成 TEXT 存库，占了全库 52% 的空间（54/103 MB）。这是数据库不该承担的角色——数据库存索引和元信息，原始行数据应在磁盘上。

三个后果：

1. **迁移数据库也无用**：同样的错误搬到 MySQL 会直接撞 `max_allowed_packet`（默认 4 MB），导不出、读不动。
2. **单行读取吃内存**：SQLite 读一行会把整个 JSON 拉进内存。测试用户已有 18 万行数据集，往后百万行级别时读一条记录即可吃掉数百 MB。
3. **数据冗余副本**：原始上传 CSV 已在 `data/` 目录（704 文件 / 135 MB），JSON 列是第二份副本。

### 1.2 次瓶颈：换库要返工 127 处

13 个 repository 模块全部直接写原生 SQL 并 import 私有函数：

```python
from 后端_核心.存储.sqlite_repo import _get_conn, _write_lock
with _get_conn() as conn:
    conn.execute("SELECT ... WHERE user_id = ? ORDER BY ... LIMIT ? OFFSET ?", (a, b))
```

127 处引用虽收敛到 `后端_核心/存储/sqlite_repo.py` 一个文件，但 SQL 方言差异散落在各处。真换 MySQL 时必须逐条改：

| 用法 | SQLite（现状） | MySQL | 位置 |
|---|---|---|---|
| 参数占位符 | `?` | `%s` | 全项目 127 处 SQL |
| 自增主键 | `INTEGER PRIMARY KEY AUTOINCREMENT` | `INT AUTO_INCREMENT PRIMARY KEY` | audit/feedback/event/usage 等建表 |
| 冲突忽略 | `INSERT OR IGNORE` | `INSERT IGNORE` | `repositories/event_repo.py:218`（支付幂等） |
| upsert | `ON CONFLICT(col) DO UPDATE` | `ON DUPLICATE KEY UPDATE` | `sqlite_repo.py:225` 等 |
| 时间字段 | TEXT（ISO 字符串） | DATETIME | 全部业务表 |

`sqlite_repo.py` 头部注释写着"只需替换本文件的实现"，但由于 repo 直接 import `_get_conn`，这个承诺无法兑现——换实现就得全改。

### 1.3 上线硬约束：写锁是进程内的

`sqlite_repo.py` 用 `_write_lock = threading.Lock()` 串行化写操作。它只保护单进程。对外服务一旦多 worker 部署（uvicorn `--workers 4` 或 gunicorn），多个进程各自持锁，SQLite 文件级写锁会直接抛 `database is locked`。当前测试环境单进程，永远复现不出来——上线必炸。

---

## 2. 目标与非目标

### 目标

1. 数据库只存元信息，数据本体落磁盘文件（parquet）
2. 引入存储后端抽象，方言差异集中收敛，换库不再逐文件返工
3. 提供 MySQL 后端（本地 Docker 实例验证），`.env` 一个开关切换
4. 上线运维基线：备份、worker 约束、健康检查

### 非目标

- 不引入 ORM 重写 127 处 SQL（收益/风险比低）
- 不改数据目录布局、不改用户上传/下载体验
- 不做分布式/分库分表（当前规模用不上）

---

## 3. 架构

```
路由 / 服务层（不动）
        │
        ▼
repositories/*_repo.py （13 个；业务 SQL 语义不变，改为统一入口）
        │
        ▼
后端_核心/存储/backend.py     ← 抽象接口：连接、占位符转换、DDL、写锁
   ├── sqlite_backend.py      ← 默认，行为与现状完全一致
   └── mysql_backend.py       ← pymysql + SQLAlchemy 连接池
        │
        ▼
数据本体：data/parquet/<dataset_id>.parquet   （DB 不再存 DataFrame）
```

### 3.1 依赖现状（已装，无需新增）

| 包 | 版本 | 用途 |
|---|---|---|
| pandas / pyarrow | 24.0.0（pyarrow） | parquet 读写 |
| pymysql | 1.4.6 | MySQL 驱动 |
| SQLAlchemy | 2.0.43 | **仅作连接池 + URL 解析**，不写 ORM |
| pytest | 已有 | 集成测试 |

---

## 4. 四步实施

### 第 1 步 · 数据本体出库

**改动**

1. `datasets` 表新增 `data_path TEXT` 列（指向 parquet 文件）
2. `保存数据集`：`df.to_parquet(data_path)`；`df_json` 列不再写入（保留列供旧数据回退读取）
3. `读取数据集`：优先 `pd.read_parquet(data_path)`，无 `data_path` 时回退 `_df_from_json(df_json)`（旧数据兼容）
4. 迁移脚本 `scripts/migrate_datasets_to_parquet.py`：把 145 行 df_json 一次性落成 parquet（幂等、可重跑、dry-run 模式）

**为什么 parquet 而不是 CSV**

- 保留 dtype：CSV 存的是字符串，读回需重新推断类型；混合类型列会猜错，下游聚合/排序出错
- 体积压缩 5-10 倍、读取快 3-5 倍（18 万行 < 1s）
- 用户可读性由**原始上传 CSV** 保障（`stored_path` 保留不动，下载/预览不受影响），两个副本各司其职

**验收**

- 现有 268 个后端测试全绿（`test_sqlite_repo.py` 的保存/读取断言更新为 parquet 路径）
- 迁移脚本跑完后 DB 体积显著下降，145 个 parquet 文件可正常读回
- 浏览器复验：上传→分析→报表→导出全链路通

### 第 2 步 · 方言抽象层

**新增 `后端_核心/存储/backend.py`**

- `db()` 上下文管理器：拿连接（SQLite 每次新建；MySQL 从池取）
- `execute(conn, sql, params)`：占位符转换。repo 层统一写 `?`；`sqlite_backend` 原样传；`mysql_backend` 内部 `?` → `%s`，并断言 SQL 中无字面问号残留
- `写锁`：SQLite 保留 `threading.Lock`；MySQL 为 no-op（靠事务与行锁）
- 各表 `CREATE TABLE` 的双后端 DDL（`AUTOINCREMENT` ↔ `AUTO_INCREMENT`）

**repo 层改动**：13 个模块的 import 改为走统一入口；业务 SQL 语义不变。

**验收（关键）**：现有 268 个后端测试**一行业务语义都不改就全绿**——这是"行为不变"的客观证据。

### 第 3 步 · MySQL 后端

- `mysql_backend.py`：SQLAlchemy 引擎仅作连接池（`mysql+pymysql://`，`pool_pre_ping=True`，池大小可配）；SQL 仍走原生
- Docker 实例（开发/验证用）：
  ```powershell
  docker run -d --name daa-mysql -p 3306:3306 -e MYSQL_ROOT_PASSWORD=rootpw `
    -e MYSQL_DATABASE=daa -e MYSQL_USER=daa_app -e MYSQL_PASSWORD=apppw `
    mysql:8.0
  ```
- `.env` 新增：`DB_BACKEND`（sqlite/mysql）、`MYSQL_HOST/PORT/USER/PASSWORD/DATABASE`
- `config/settings.py` 的 `EnvConfig` 补对应字段
- 迁移脚本 `scripts/migrate_sqlite_to_mysql.py`：读 SQLite 元信息 + parquet 文件 → 写 MySQL 表 + 复制文件；时间字段 TEXT ISO → DATETIME
- 测试 `tests/backend/test_mysql_backend.py`：连 Docker 真实跑；无实例时 `skipif` 自动跳过（CI 不假红）

**验收**：SQLite 模式全绿 + MySQL 模式同套测试绿；切换只改 `.env` 一个开关，SQLite 可随时切回

### 第 4 步 · 上线运维基线

- **备份**：`scripts/backup_db.py` 扩展——SQLite 复制文件（已有）；MySQL 用 `mysqldump`，加定时与保留策略
- **worker 约束**：SQLite 模式启动脚本固定 `--workers 1`（进程内写锁，多 worker 会撞锁）；MySQL 模式可多 worker
- **健康检查**：补充 `/healthz` 返回后端类型与数据库连通状态

---

## 5. 风险与应对

| 风险 | 影响 | 应对 |
|---|---|---|
| 第 1 步破坏读取链路 | 分析功能不可用 | 保留 `df_json` 回退路径；测试先红后绿；先写读取测试 |
| parquet 与原 CSV 类型不一致 | 下游聚合结果变化 | 迁移脚本逐个对比读取行数/列名/dtype，报告差异 |
| 占位符替换误伤字面问号 | SQL 语法错误 | 替换前断言无字面 `?`；SQL 规范禁止在 SQL 中写字面问号 |
| MySQL 时间字段类型转换错 | 排序/筛选错 | 迁移脚本显式转换 + 时区一致性测试 |
| 抽象层侵入业务逻辑 | 回归失败 | 验收标准即"现有测试一行不改全绿" |
| 多 worker + SQLite 撞写锁 | 上线 500 错误 | 第 4 步 worker 约束写进启动脚本；MySQL 后端消除此风险 |

---

## 6. 迁移与回滚

- 四步各自独立可上线、可回滚
- 第 1/2 步不改动用户数据文件（原始 CSV 不动）
- 第 3 步切库前强制备份 SQLite 文件；切换只改 `.env`；SQLite 数据仍在，随时切回
- 建议顺序：第 1 步上线观察 → 第 2 步上线 → 第 4 步上线运维基线 → 第 3 步（MySQL）按需启用

---

## 7. 验证总表

| 步骤 | 自动化验证 | 浏览器复验 |
|---|---|---|
| 1 出库 | 268 全绿 + 迁移脚本报告 | 上传→分析→报表→导出 |
| 2 抽象 | 268 全绿（业务 SQL 未改） | 全链路冒烟 |
| 3 MySQL | SQLite 全绿 + MySQL 同套全绿 | MySQL 模式下全链路 |
| 4 运维 | 备份脚本测试；/healthz 测试 | — |

---

## 8. 待确认

- [ ] 无（选型已定：路径 1 / 本地 Docker / parquet / SQLAlchemy 当连接池）
- 评审通过后进入实现计划（writing-plans）