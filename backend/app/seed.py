from datetime import datetime, timezone

from app.db import 连接

建表 = """
CREATE TABLE IF NOT EXISTS 重叠日窗票表 (
  编号 INTEGER PRIMARY KEY AUTOINCREMENT,
  票号 TEXT, 源键 TEXT, 目标键 TEXT, 重叠日 TEXT, 形态 TEXT, 状态 TEXT,
  时刻 TEXT NOT NULL DEFAULT '',
  载荷 TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS 台参 (
  键 TEXT PRIMARY KEY,
  值 TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS 账户 (
  账户键 TEXT PRIMARY KEY,
  户名 TEXT NOT NULL,
  币种 TEXT NOT NULL DEFAULT 'CNY',
  开户营业日 TEXT NOT NULL,
  状态 TEXT NOT NULL DEFAULT '正常',
  并户去向 TEXT NOT NULL DEFAULT '',
  并户凭证 TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS 变动流水 (
  流水号 TEXT PRIMARY KEY,
  账户键 TEXT NOT NULL,
  营业日 TEXT NOT NULL,
  发生时 TEXT NOT NULL,
  变动额 INTEGER NOT NULL,
  摘要 TEXT NOT NULL DEFAULT '',
  批次编号 TEXT NOT NULL DEFAULT '',
  命运 TEXT NOT NULL DEFAULT '已入账',
  原账户键 TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS 抽取批次 (
  编号 TEXT PRIMARY KEY,
  营业日 TEXT NOT NULL,
  时刻 TEXT NOT NULL,
  报告 TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS 周期快照 (
  快照键 TEXT PRIMARY KEY,
  账户键 TEXT NOT NULL,
  营业日 TEXT NOT NULL,
  余额 INTEGER NOT NULL,
  抽取批次编号 TEXT NOT NULL,
  来源 TEXT NOT NULL DEFAULT '日终抽取',
  状态 TEXT NOT NULL DEFAULT '有效',
  UNIQUE(账户键, 营业日)
);
CREATE TABLE IF NOT EXISTS 回放批次 (
  编号 TEXT PRIMARY KEY,
  营业日 TEXT NOT NULL,
  时刻 TEXT NOT NULL,
  报告 TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS 差额行 (
  编号 INTEGER PRIMARY KEY AUTOINCREMENT,
  回放批次编号 TEXT NOT NULL,
  账户键 TEXT NOT NULL,
  营业日 TEXT NOT NULL,
  快照余额 INTEGER,
  回放余额 INTEGER,
  差额 INTEGER NOT NULL,
  原因 TEXT NOT NULL,
  状态 TEXT NOT NULL DEFAULT '有效',
  时刻 TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS 断档记录 (
  编号 INTEGER PRIMARY KEY AUTOINCREMENT,
  账户键 TEXT NOT NULL,
  缺营业日 TEXT NOT NULL,
  检出批次编号 TEXT NOT NULL,
  处置 TEXT NOT NULL DEFAULT '待处理',
  时刻 TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS 跳变记录 (
  编号 INTEGER PRIMARY KEY AUTOINCREMENT,
  账户键 TEXT NOT NULL,
  营业日 TEXT NOT NULL,
  前日余额 INTEGER,
  当日余额 INTEGER,
  流水净额 INTEGER,
  偏离 INTEGER NOT NULL,
  检出批次编号 TEXT NOT NULL,
  时刻 TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS 旁置簿 (
  编号 INTEGER PRIMARY KEY AUTOINCREMENT,
  原因 TEXT NOT NULL,
  账户键 TEXT NOT NULL DEFAULT '',
  营业日 TEXT NOT NULL DEFAULT '',
  载荷 TEXT NOT NULL,
  时刻 TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS 装载批次 (
  编号 TEXT PRIMARY KEY,
  时刻 TEXT NOT NULL,
  报告 TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS 并户凭证 (
  凭证编号 TEXT PRIMARY KEY,
  源账户键 TEXT NOT NULL,
  目标账户键 TEXT NOT NULL,
  生效日 TEXT NOT NULL,
  源末镜日 TEXT NOT NULL,
  源结转余额 INTEGER NOT NULL,
  源键暴露 INTEGER NOT NULL DEFAULT 1,
  状态 TEXT NOT NULL DEFAULT '有效',
  报告 TEXT NOT NULL DEFAULT '{}',
  时刻 TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS 快照_户_状态 ON 周期快照(账户键, 状态, 营业日);
CREATE INDEX IF NOT EXISTS 流水_户_日 ON 变动流水(账户键, 营业日);
CREATE INDEX IF NOT EXISTS 凭证_源 ON 并户凭证(源账户键, 状态);
CREATE INDEX IF NOT EXISTS 凭证_目标 ON 并户凭证(目标账户键, 状态);
"""


补列 = [
    ("账户", "并户去向", "TEXT NOT NULL DEFAULT ''"),
    ("账户", "并户凭证", "TEXT NOT NULL DEFAULT ''"),
    ("变动流水", "原账户键", "TEXT NOT NULL DEFAULT ''"),
    ("差额行", "状态", "TEXT NOT NULL DEFAULT '有效'"),
]


def _补列(conn) -> None:
    for 表, 列, 定义 in 补列:
        已有 = {r["name"] for r in conn.execute(f"PRAGMA table_info({表})")}
        if 列 not in 已有:
            conn.execute(f"ALTER TABLE {表} ADD COLUMN {列} {定义}")

空桩模块 = [
    "开户首日无前日",
    "同日重复抽取幂等",
    "流水迟到补抽",
    "销户终镜",
    "负余额闸",
    "币种隔离",
    "半截抽取回滚",
    "快照封印写闸",
    "回放权威择定",
    "断档补齐",
    "断档旁置",
    "跳变阈值",
    "账户分片抽取",
    "抽取时钟漂移",
    "流水序缺口",
    "子户汇总镜",
    "假期跳日日历",
    "差额分桶",
    "三日连环守恒",
    "抽取重试预算",
    "跨日切点策略",
]


种子账户 = [
    ("户甲", "甲收单户", "2026-11-01"),
    ("户乙", "乙结算户", "2026-11-01"),
    ("户丙", "丙备用户", "2026-11-05"),
]


def 写入种子账户(conn) -> None:
    for 键, 名, 日 in 种子账户:
        conn.execute(
            "INSERT INTO 账户(账户键, 户名, 币种, 开户营业日, 状态) VALUES (?,?,?,?,?)",
            (键, 名, "CNY", 日, "正常"),
        )


def 此刻() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def 初始化库() -> None:
    conn = 连接()
    conn.executescript(建表)
    _补列(conn)
    if conn.execute("SELECT COUNT(*) AS c FROM 台参").fetchone()["c"] == 0:
        for k, v in {
            "站名": "日镜账",
            "骨架": "日终余额抽取→周期快照落行→变动流水回放核对→断档跳变检出→快照与回放差额清单",
            "跳变阈值分": "0",
            "断档处置": "记断档并继续",
            "缺前日策略": "以零为开端",
            "重复抽取": "盖写同日快照",
            "并户口径": "源键只读归档",
            "重叠窗票口径": "窗票强制坍缩",
        }.items():
            conn.execute("INSERT INTO 台参(键, 值) VALUES (?, ?)", (k, v))
    if conn.execute("SELECT COUNT(*) AS c FROM 账户").fetchone()["c"] == 0:
        写入种子账户(conn)
    conn.commit()
    conn.close()
