"""
db/database.py —— SQLite 轻量数据库模块（建表 + 连接管理）

设计说明（毕业论文可引用）：
  1. 本项目为轻量化毕设，不引入 SQLAlchemy 等 ORM 框架，直接使用标准库 sqlite3；
  2. 数据库共 4 张表：
     - judge_records    判题主表：一份答卷一条记录（含总分、错误统计、完整JSON）
     - problem_details  每题明细表：一道题一条记录（用于界面2按题/按知识点统计）
     - knowledge_stats  知识点聚合表：知识点出现次数/错误次数/错误率（用于图谱标红）
     - meta             元信息表：记录 schema 版本，便于后续结构升级
  3. 表间关系：judge_records 1 —— N problem_details（外键 + 级联删除）
  4. 所有 JSON 字段以 TEXT 存储（json.dumps / json.loads 转换），
     避免额外依赖，同时保留完整结构化信息，便于导出与二次分析。
"""
import json
import os
import sqlite3
import sys
from typing import Optional

# ---------- 数据库文件位置（默认 backend/data/answer_mark.db，可在 config.py 中修改） ----------
THIS_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.dirname(THIS_DIR)
_DEFAULT_DB = os.path.join(BACKEND_DIR, "data", "answer_mark.db")
try:
    if BACKEND_DIR not in sys.path:
        sys.path.insert(0, BACKEND_DIR)
    import config as _cfg
    DB_FILE = getattr(_cfg, "DB_FILE", _DEFAULT_DB)
except Exception:          # 配置不可用时回退到默认路径，保证模块可独立运行
    DB_FILE = _DEFAULT_DB

# 表结构版本号（结构变更时 +1，便于迁移判断）
SCHEMA_VERSION = "1.0.0"


# ============================================================
# 一、建表语句（DDL）
# ============================================================
DDL_JUDGE_RECORDS = """
CREATE TABLE IF NOT EXISTS judge_records (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,  -- 主键，自增
    image_name        TEXT    NOT NULL,                   -- 答卷文件名（原始上传名）
    image_path        TEXT,                               -- 图片在服务器上的存储路径
    image_md5         TEXT,                               -- 图片MD5（去重/溯源）
    full_score        REAL    NOT NULL DEFAULT 0,         -- 本题满分（每题满分×题数=总满分）
    total_score       REAL    NOT NULL DEFAULT 0,         -- 实际总得分
    score_rate        REAL    NOT NULL DEFAULT 0,         -- 得分率 = total/full（0~1）
    problem_count     INTEGER NOT NULL DEFAULT 0,         -- 本答卷包含题目数
    is_multi_problem  INTEGER NOT NULL DEFAULT 0,         -- 是否多题页（1=是）
    error_logic       INTEGER NOT NULL DEFAULT 0,         -- 逻辑漏洞数量
    error_calculation INTEGER NOT NULL DEFAULT 0,         -- 计算错误数量
    error_concept     INTEGER NOT NULL DEFAULT 0,         -- 概念错误数量
    weak_points       TEXT,                               -- 薄弱知识点 JSON 数组
    detail_json       TEXT,                               -- 完整判题结果 JSON（M1/M2/M3）
    feedback          TEXT,                               -- 模型生成的教学反馈文本
    is_pass           INTEGER NOT NULL DEFAULT 0,         -- 是否及格（1/0，阈值见 config）
    duration_ms       INTEGER NOT NULL DEFAULT 0,         -- 判题耗时（毫秒）
    created_at        TEXT    NOT NULL                    -- 提交时间（ISO8601）
);
"""

DDL_PROBLEM_DETAILS = """
CREATE TABLE IF NOT EXISTS problem_details (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    record_id        INTEGER NOT NULL,          -- 外键：所属答卷记录
    problem_index    INTEGER NOT NULL,          -- 第几题（1,2,3...）
    problem_text     TEXT,                      -- 题目/学生作答原文摘要
    score            REAL    DEFAULT 0,         -- 本题得分
    full_score       REAL    DEFAULT 0,         -- 本题满分
    verdict          TEXT,                      -- 本题判定：correct/incorrect/uncertain
    error_reasons    TEXT,                      -- 本题错误原因 JSON 数组
    knowledge_points TEXT,                      -- 本题涉及知识点 JSON 数组
    steps_json       TEXT,                      -- 本题解题步骤 JSON 数组
    FOREIGN KEY (record_id) REFERENCES judge_records(id) ON DELETE CASCADE
);
"""

DDL_KNOWLEDGE_STATS = """
CREATE TABLE IF NOT EXISTS knowledge_stats (
    node_id      TEXT PRIMARY KEY,              -- 知识图谱节点ID（与 knowledge_data.json 对应）
    node_name    TEXT,                          -- 知识点名称
    total_count  INTEGER NOT NULL DEFAULT 0,    -- 被考核总次数（出现该知识点的题数）
    error_count  INTEGER NOT NULL DEFAULT 0,    -- 出错次数
    error_rate   REAL    NOT NULL DEFAULT 0,    -- 错误率 = error_count / total_count
    updated_at   TEXT                           -- 最近更新时间
);
"""

DDL_META = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""

# 索引：加速界面2的统计查询（按时间排序、按分数筛选、按记录查明细）
DDL_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_records_created   ON judge_records(created_at DESC);",
    "CREATE INDEX IF NOT EXISTS idx_records_score     ON judge_records(total_score);",
    "CREATE INDEX IF NOT EXISTS idx_records_md5       ON judge_records(image_md5);",
    "CREATE INDEX IF NOT EXISTS idx_problem_record    ON problem_details(record_id);",
    "CREATE INDEX IF NOT EXISTS idx_problem_knowledge ON problem_details(problem_index);",
]

# 全部 DDL（建表顺序：先主表，后子表）
ALL_DDL = [DDL_JUDGE_RECORDS, DDL_PROBLEM_DETAILS, DDL_KNOWLEDGE_STATS, DDL_META]


# ============================================================
# 二、连接管理
# ============================================================
def get_conn(db_file: Optional[str] = None) -> sqlite3.Connection:
    """
    获取数据库连接。
      - row_factory 设为 sqlite3.Row，查询结果可像字典一样按列名取值
      - 开启外键约束（SQLite 默认关闭），保证级联删除生效
      - 开启 WAL 日志模式，提高读写并发能力（FastAPI 多线程访问更稳）
    """
    path = db_file or DB_FILE
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    try:
        conn.execute("PRAGMA journal_mode = WAL;")
    except sqlite3.DatabaseError:
        pass
    return conn


# ============================================================
# 三、初始化（建表）
# ============================================================
def init_db(db_file: Optional[str] = None, verbose: bool = False) -> str:
    """
    初始化数据库：创建全部表与索引，写入 schema 版本号。
    可重复执行（IF NOT EXISTS），不会覆盖已有数据。

    返回：数据库文件绝对路径
    """
    path = db_file or DB_FILE
    conn = get_conn(path)
    try:
        cur = conn.cursor()
        for ddl in ALL_DDL:
            cur.execute(ddl)
        for idx in DDL_INDEXES:
            cur.execute(idx)
        # 记录 schema 版本
        cur.execute(
            "INSERT INTO meta(key, value) VALUES('schema_version', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value;",
            (SCHEMA_VERSION,),
        )
        conn.commit()
        if verbose:
            tables = [r["name"] for r in cur.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;"
            ).fetchall()]
            print(f"[DB] 初始化完成: {path}")
            print(f"[DB] 数据表: {', '.join(tables)}")
    finally:
        conn.close()
    return path


def table_info(db_file: Optional[str] = None) -> dict:
    """
    查看表结构（调试用）：返回 {表名: [列信息, ...]}
    """
    conn = get_conn(db_file)
    try:
        result = {}
        tables = [r["name"] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name;"
        ).fetchall()]
        for t in tables:
            cols = conn.execute(f"PRAGMA table_info({t});").fetchall()
            result[t] = [
                {"name": c["name"], "type": c["type"], "pk": bool(c["pk"]), "notnull": bool(c["notnull"])}
                for c in cols
            ]
        return result
    finally:
        conn.close()


# ============================================================
# 四、JSON 字段辅助函数（写入/读取时统一转换）
# ============================================================
def to_json(obj) -> str:
    """Python 对象 -> JSON 字符串（中文不转义，便于人工查看）"""
    return json.dumps(obj, ensure_ascii=False)


def from_json(text, default=None):
    """JSON 字符串 -> Python 对象（解析失败返回默认值，保证健壮性）"""
    if not text:
        return default if default is not None else []
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return default if default is not None else []


# ============================================================
# 五、演示测试数据（毕设答辩用：不调 API 也能让界面2有数据可看）
# ============================================================
# 使用场景：答辩/截图前，先造一批模拟判题记录，让学情统计页面
# （KPI 卡片、趋势图、分布图、知识点掌握度、图谱标红）全部有内容可展示。
#
# 用法（在 backend 目录下执行）：
#   python db/database.py --seed           数据库为空时插入演示数据
#   python db/database.py --seed --force   清空演示相关表后重新插入（真实数据也会被清！）
#
# 演示数据特点：
#   - 15 份答卷，时间分布在最近 30 天（趋势图有起伏）
#   - 得分率覆盖 0.2 ~ 1.0 各区间（分布直方图每桶都有）
#   - 三种错误类型（逻辑/计算/概念）都有出现（错题统计有意义）
#   - 单题页 + 多题页混合（多题统计有意义）
#   - 知识点 ID 与 knowledge_data.json 完全一致（图谱节点能正确标红）

def seed_demo_data(db_file: Optional[str] = None, force: bool = False) -> int:
    """
    插入演示测试数据。返回插入的记录条数。
      - 已存在演示数据（image_md5 以 demo_ 开头）时跳过，避免重复插入
      - 真实判题记录始终保留，演示数据以"追加"方式混入（学情页面数据更丰富）
      - force=True 时清空全部业务表（含真实数据！）后只插入演示数据
    """
    path = db_file or DB_FILE
    conn = get_conn(path)
    cur = conn.cursor()
    try:
        if force:
            cur.execute("DELETE FROM judge_records;")      # 子表有级联删除，会一并清掉
            cur.execute("DELETE FROM knowledge_stats;")
        else:
            # 已插过演示数据则跳过（真实记录不受影响，允许追加共存）
            cur.execute("SELECT COUNT(*) AS n FROM judge_records WHERE image_md5 LIKE 'demo\\_%' ESCAPE '\\';")
            if cur.fetchone()["n"] > 0:
                print("[DB] 演示数据已存在，跳过（如需重置请加 --force，注意会清空全部记录）")
                return 0

        from datetime import datetime, timedelta

        # ---- 演示数据定义 ----
        # 每条 = 一份答卷：(天数前, 文件名, 题目列表)
        # 每题 = (题目摘要, 得分, 满分, 判定, 涉及知识点ID, 错误类型计数{logic/calc/concept}, 薄弱点ID)
        _now = datetime.now()
        demo_papers = [
            (29, "demo_张三_月考数学.jpg", [
                ("解方程 2x+3=11", 9, 10, "correct",   ["MATH-BASIC-OP", "MATH-LIN-1V"], {}, []),
            ]),
            (28, "demo_李四_课后作业1.jpg", [
                ("解方程 3x-5=10", 6, 10, "uncertain", ["MATH-LIN-1V"], {"calc": 1}, ["MATH-LIN-1V"]),
            ]),
            (27, "demo_王五_单元测试A.jpg", [
                ("解方程组 x+y=5, x-y=1", 8, 10, "correct", ["MATH-LIN-2V", "MATH-LIN-1V"], {}, []),
                ("求函数 y=2x+1 的斜率", 10, 10, "correct", ["MATH-FUNC-LIN", "MATH-FUNC-CONCEPT"], {}, []),
            ]),
            (25, "demo_张三_课后作业2.jpg", [
                ("解一元二次方程 x^2-5x+6=0", 4, 10, "incorrect", ["MATH-QUAD-1V", "MATH-BASIC-OP"],
                 {"concept": 1, "calc": 1}, ["MATH-QUAD-1V"]),
            ]),
            (23, "demo_赵六_随堂练习.jpg", [
                ("计算 12+8×3", 10, 10, "correct", ["MATH-BASIC-OP"], {}, []),
            ]),
            (21, "demo_李四_周测卷.jpg", [
                ("解方程 5(x-2)=15", 7, 10, "uncertain", ["MATH-LIN-1V", "MATH-EQ-PROP"], {"logic": 1}, ["MATH-EQ-PROP"]),
                ("画二次函数 y=x^2 图像", 5, 10, "incorrect", ["MATH-FUNC-QUAD"], {"concept": 1}, ["MATH-FUNC-QUAD"]),
            ]),
            (18, "demo_王五_课后作业3.jpg", [
                ("求三角形内角和证明", 8, 10, "correct", ["MATH-GEOM-TRIANGLE"], {}, []),
            ]),
            (16, "demo_钱七_编程作业.jpg", [
                ("写 Python 循环求 1~100 和", 3, 10, "incorrect", ["PROG-LOOP", "PROG-VAR"],
                 {"logic": 1, "calc": 1}, ["PROG-LOOP"]),
            ]),
            (14, "demo_张三_周测卷.jpg", [
                ("解方程 4x+7=19", 9, 10, "correct", ["MATH-LIN-1V"], {}, []),
                ("求 sin30° 的值", 8, 10, "correct", ["MATH-TRIG-BASIC"], {}, []),
            ]),
            (11, "demo_赵六_月考数学.jpg", [
                ("解方程组 2x+y=8, x-y=1", 6, 10, "uncertain", ["MATH-LIN-2V"], {"calc": 2}, ["MATH-LIN-2V", "MATH-BASIC-OP"]),
            ]),
            (9,  "demo_李四_课后作业4.jpg", [
                ("求圆的周长（r=3）", 10, 10, "correct", ["MATH-GEOM-CIRCLE"], {}, []),
            ]),
            (7,  "demo_钱七_函数专题卷.jpg", [
                ("判断函数单调性", 2, 10, "incorrect", ["MATH-FUNC-CONCEPT", "MATH-FUNC-LIN"],
                 {"concept": 1}, ["MATH-FUNC-CONCEPT"]),
            ]),
            (5,  "demo_王五_课后作业5.jpg", [
                ("写 Python 函数判断奇偶", 7, 10, "uncertain", ["PROG-FUNC", "PROG-COND"], {"logic": 1}, ["PROG-COND"]),
            ]),
            (3,  "demo_张三_模拟卷.jpg", [
                ("解一元二次方程 x^2+4x+4=0", 9, 10, "correct", ["MATH-QUAD-1V"], {}, []),
                ("求抛物线顶点坐标", 8, 10, "correct", ["MATH-FUNC-QUAD", "MATH-FUNC-LIN"], {}, []),
                ("计算 15-3×4", 10, 10, "correct", ["MATH-BASIC-OP"], {}, []),
            ]),
            (1,  "demo_赵六_期末模拟.jpg", [
                ("综合题：方程+函数图像", 6, 10, "uncertain", ["MATH-LIN-1V", "MATH-FUNC-LIN"],
                 {"calc": 1, "logic": 1}, ["MATH-FUNC-LIN"]),
            ]),
        ]

        # ---- 写入 judge_records + problem_details ----
        kp_total = {}   # 知识点聚合：node_id -> [node_name, 总次数, 错误次数]
        inserted = 0
        for days_ago, fname, problems in demo_papers:
            total = sum(p[1] for p in problems)
            full = sum(p[2] for p in problems)
            rate = round(total / full, 4) if full else 0
            e_logic = sum(p[5].get("logic", 0) for p in problems)
            e_calc = sum(p[5].get("calc", 0) for p in problems)
            e_concept = sum(p[5].get("concept", 0) for p in problems)
            weak = []
            for p in problems:
                weak.extend(p[6])
            weak = sorted(set(weak))
            created = (_now - timedelta(days=days_ago)).isoformat(timespec="seconds")

            cur.execute("""
                INSERT INTO judge_records (
                    image_name, image_path, image_md5, full_score, total_score, score_rate,
                    problem_count, is_multi_problem, error_logic, error_calculation, error_concept,
                    weak_points, detail_json, feedback, is_pass, duration_ms, created_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                fname, f"data/uploads/demo_{days_ago}.jpg", f"demo_md5_{days_ago}",
                full, total, rate,
                len(problems), 1 if len(problems) > 1 else 0,
                e_logic, e_calc, e_concept,
                to_json(weak),
                to_json({"demo": True, "note": "演示测试数据"}),
                f"【演示数据】{fname}：得分 {total}/{full}，"
                + (f"错误统计 逻辑{e_logic}/计算{e_calc}/概念{e_concept}。" if (e_logic + e_calc + e_concept) else "全部正确，保持良好。"),
                1 if rate >= 0.6 else 0,
                45000 + days_ago * 137,
                created,
            ))
            rid = cur.lastrowid
            inserted += 1

            for i, (text, sc, fs, verdict, kps, errs, _) in enumerate(problems, 1):
                cur.execute("""
                    INSERT INTO problem_details (
                        record_id, problem_index, problem_text, score, full_score,
                        verdict, error_reasons, knowledge_points, steps_json
                    ) VALUES (?,?,?,?,?,?,?,?,?)
                """, (
                    rid, i, text, sc, fs, verdict,
                    to_json([f"{k}错误" for k in errs]),
                    to_json(kps),
                    to_json([{"step_id": 1, "content": "（演示数据：略）", "verdict": verdict}]),
                ))
                # 聚合知识点统计
                for kp in kps:
                    if kp not in kp_total:
                        kp_total[kp] = [kp, 0, 0]
                    kp_total[kp][1] += 1
                    if verdict != "correct":
                        kp_total[kp][2] += 1

        # ---- 写入 knowledge_stats（图谱标红数据源）----
        now_iso = _now.isoformat(timespec="seconds")
        node_names = {
            "MATH-BASIC-OP": "四则运算", "MATH-EQ-PROP": "等式基本性质",
            "MATH-LIN-1V": "一元一次方程求解", "MATH-LIN-2V": "二元一次方程组求解",
            "MATH-QUAD-1V": "一元二次方程求解", "MATH-FUNC-CONCEPT": "函数基本概念",
            "MATH-FUNC-LIN": "一次函数", "MATH-FUNC-QUAD": "二次函数",
            "MATH-TRIG-BASIC": "三角函数基础", "MATH-GEOM-CIRCLE": "圆的基本性质",
            "MATH-GEOM-TRIANGLE": "三角形性质", "PROG-VAR": "变量与赋值",
            "PROG-LOOP": "循环结构", "PROG-COND": "条件分支", "PROG-FUNC": "函数定义与调用",
        }
        for nid, (name, tot, err) in kp_total.items():
            cur.execute("""
                INSERT INTO knowledge_stats (node_id, node_name, total_count, error_count, error_rate, updated_at)
                VALUES (?,?,?,?,?,?)
                ON CONFLICT(node_id) DO UPDATE SET
                    total_count = total_count + excluded.total_count,
                    error_count = error_count + excluded.error_count,
                    error_rate  = (error_count + excluded.error_count) * 1.0 / (total_count + excluded.total_count),
                    updated_at  = excluded.updated_at
            """, (nid, node_names.get(nid, nid), tot, err,
                  round(err / tot, 4) if tot else 0.0, now_iso))

        conn.commit()
        print(f"[DB] 演示数据插入完成：{inserted} 份答卷，{len(kp_total)} 个知识点统计")
        return inserted
    except Exception as e:
        conn.rollback()
        print(f"[DB] 演示数据插入失败: {e}")
        return 0
    finally:
        conn.close()


# ============================================================
# 六、直接运行本文件：建表 / 插入演示数据 / 打印表结构
# ============================================================
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="数据库初始化与演示数据工具")
    parser.add_argument("--seed", action="store_true", help="插入演示测试数据（数据库为空时才生效）")
    parser.add_argument("--force", action="store_true", help="配合 --seed：清空已有数据后重新插入")
    args = parser.parse_args()

    print("=" * 60)
    print("SQLite 数据库初始化（建表）")
    print("=" * 60)
    db_path = init_db(verbose=True)

    if args.seed:
        print("-" * 60)
        seed_demo_data(force=args.force)

    print("-" * 60)
    for table, cols in table_info().items():
        print(f"\n表 {table}:")
        for c in cols:
            flag = " PK" if c["pk"] else (" NOT NULL" if c["notnull"] else "")
            print(f"    - {c['name']:<20} {c['type']:<8}{flag}")
    print("\n" + "=" * 60)
    print("完成 ✓")
