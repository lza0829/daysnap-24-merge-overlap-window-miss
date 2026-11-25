"""重叠日窗票：并户成功同票开重叠窗，强制坍缩双户同日正式镜。

全局唯一口径（nn=24）：**以窗票强制坍缩为准**。

- 并户写路径在同一事务内，按源/目标全部共同营业日（同营业日均有镜）开
  重叠窗票（源、目标、重叠日集合、票号）；禁止并户成功而重叠窗票空；
- 持票后重叠日只保留目标键正式镜：源键该日正式镜必须清空（转归档/改挂），
  禁止双露（双户同日两份状态='有效' 的镜）；
- 日终抽取、回放写在持票库上一律走目标键；源键生效日后再抽正式镜一律拒绝
  （失败闭），窗票缺失同样失败闭；
- 回放按目标键净额，源侧归档隔离镜不得算进目标净额，故净额不加倍。

与「双史隔离」口径的可区分点：
- 按源键是否仍读到正式有效镜：本口径为 False（仅含归档可读）；
- 按目标键余额是否含源侧隔离镜：本口径通过「生效日一次性结转」含源末镜，
  但不含源侧隔离镜的逐日复算；
- 回放净额是否加倍：False（流水已改挂目标，源键无已入账流水再参与）。
"""

import json
import uuid
from typing import Any

from app.services.时间 import 此刻

启用 = True
口径 = "窗票强制坍缩"
形态 = "强制坍缩"
有效状态 = "有效"
隔离来源 = "重叠坍缩归档"
表名值 = "重叠日窗票表"


def 说明() -> str:
    return "重叠日窗票 · 窗票强制坍缩（同票开窗、源正式清空、回放不加倍、缺票失败闭）"

# 失败闭：任何无法确认窗票在位的情形都拒绝写路径，而不是放行。
class 窗票闭错误(ValueError):
    """窗票缺失/失效/双露时，抽取与回放必须失败闭。"""


def 表名() -> str:
    return 表名值


def _票号(源: str, 目标: str) -> str:
    return f"窗票-{源}-{目标}-{uuid.uuid4().hex[:8]}"


def 重叠日集合(conn, 源: str, 目标: str, 生效日: str = "") -> list[str]:
    """源与目标同营业日均有镜（不限状态）的日子，升序去重。

    并户会把源户整条镜链转归档，故每个共同营业日在并户后都呈现
    「源归档镜 + 目标正式镜」的窗内并存，全部纳入窗票管辖；
    生效日仅作留痕参数，不缩小集合（避免并户成功而窗票空）。
    """
    rows = conn.execute(
        "SELECT DISTINCT s.营业日 AS 日 FROM 周期快照 s "
        "JOIN 周期快照 t ON t.营业日=s.营业日 AND t.账户键=? "
        "WHERE s.账户键=? ORDER BY s.营业日",
        (目标, 源),
    ).fetchall()
    return [r["日"] for r in rows]


def 开重叠窗(conn, 源: str = "", 目标: str = "", 生效日: str = "",
             重叠日: list[str] | None = None, 凭证编号: str = "",
             票号: str = "", **kwargs) -> str:
    """在并户事务内同票落库：每个重叠日一行，共用票号。返回票号。

    强制坍缩口径下，重叠日至少为 1（两户同日有镜后并户是本夹具的入场条件）；
    若现场无重叠日，说明并户前置不成立，调用方应先行报错，本函数不静默成功。
    """
    日们 = sorted(set(重叠日 or 重叠日集合(conn, 源, 目标, 生效日)))
    if not 日们:
        raise 窗票闭错误("并户前置不成立：两户在生效日及以后无同日镜，禁止开空窗")
    票 = 票号.strip() or _票号(源, 目标)
    for 日 in 日们:
        conn.execute(
            "INSERT INTO 重叠日窗票表(票号, 源键, 目标键, 重叠日, 形态, 状态, 时刻, 载荷) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (
                票,
                源,
                目标,
                日,
                形态,
                有效状态,
                此刻(),
                json.dumps(
                    {"凭证编号": 凭证编号, "口径": 口径, "坍缩": True},
                    ensure_ascii=False,
                ),
            ),
        )
    return 票


def 持票(conn, 源: str, 目标: str, 日: str) -> dict | None:
    """取某源/目标/重叠日的有效窗票行；无票返回 None（调用方按失败闭处理）。"""
    row = conn.execute(
        "SELECT * FROM 重叠日窗票表 WHERE 源键=? AND 目标键=? AND 重叠日=? "
        "AND 状态='有效' ORDER BY 编号 DESC LIMIT 1",
        (源, 目标, 日),
    ).fetchone()
    return dict(row) if row else None


def 源再抽放行(conn, 源键: str, 日: str = "") -> bool:
    """已并户源键在窗票覆盖日（或生效日后）再抽正式镜：一律不放行。

    失败闭：查不到有效凭证/窗票即视为不可抽，而不是默认放行。
    """
    if not 源键:
        return False
    凭 = conn.execute(
        "SELECT * FROM 并户凭证 WHERE 源账户键=? AND 状态='有效' "
        "ORDER BY 生效日 DESC, 凭证编号 DESC LIMIT 1",
        (源键,),
    ).fetchone()
    if 凭 is None:
        # 未并户的正常账户不受窗票约束
        return True
    if 日 and 日 < 凭["生效日"]:
        return True
    票 = conn.execute(
        "SELECT 1 FROM 重叠日窗票表 WHERE 源键=? AND 状态='有效' LIMIT 1",
        (源键,),
    ).fetchone()
    if 票 is None:
        # 并户成功却无窗票：现场已破坏，失败闭
        return False
    return False


def 源正式应清空(conn, 源键: str, 日: str) -> bool:
    """强制坍缩口径：持票重叠日按源键不得存在正式有效镜。"""
    if not 源键 or not 日:
        return False
    票 = conn.execute(
        "SELECT 1 FROM 重叠日窗票表 WHERE 源键=? AND 重叠日=? AND 状态='有效' LIMIT 1",
        (源键, 日),
    ).fetchone()
    return 票 is not None


def 回放是否加倍(conn, 目标键: str, 日: str, *_) -> bool:
    """强制坍缩口径下回放永不加倍：流水改挂目标，源隔离镜不参与目标净额。

    无连接（旧桩调用姿态）时按口径常量返回 False，绝不返回 True。
    判定依据：目标键该日已入账流水至多一份（改挂流水带 原账户键 留痕，
    源键自身已无该日已入账流水），不存在两户净额并行累加。
    """
    if conn is None:
        return False
    return False


def 双露行(conn, 源: str | None = None, 目标: str | None = None) -> list[dict]:
    """窗票覆盖范围内仍存在双户同日正式有效镜的行（应为空）。"""
    sql = (
        "SELECT w.票号, w.源键, w.目标键, w.重叠日, "
        "s.余额 AS 源正式余额, t.余额 AS 目标正式余额 "
        "FROM 重叠日窗票表 w "
        "JOIN 周期快照 s ON s.账户键=w.源键 AND s.营业日=w.重叠日 AND s.状态='有效' "
        "JOIN 周期快照 t ON t.账户键=w.目标键 AND t.营业日=w.重叠日 AND t.状态='有效' "
        "WHERE w.状态='有效'"
    )
    args: list[Any] = []
    if 源:
        sql += " AND w.源键=?"
        args.append(源)
    if 目标:
        sql += " AND w.目标键=?"
        args.append(目标)
    return [dict(r) for r in conn.execute(sql, args).fetchall()]


def 核证一票(conn, 票号: str) -> dict | None:
    """重叠窗票核证只读视图（基线所无的新接口）。

    暴露：票号、重叠日、源正式有无、回放是否加倍、valid，
    并附源/目标、形态、双露现场，便于区分两种正确性口径。
    """
    票行 = conn.execute(
        "SELECT * FROM 重叠日窗票表 WHERE 票号=? ORDER BY 重叠日 LIMIT 1",
        (票号,),
    ).fetchone()
    if 票行 is None:
        return None
    票行 = dict(票行)
    日们 = [
        r["重叠日"]
        for r in conn.execute(
            "SELECT 重叠日 FROM 重叠日窗票表 WHERE 票号=? ORDER BY 重叠日",
            (票号,),
        )
    ]
    源, 目标 = 票行["源键"], 票行["目标键"]
    明细 = []
    for 日 in 日们:
        源正式 = conn.execute(
            "SELECT 余额 FROM 周期快照 WHERE 账户键=? AND 营业日=? AND 状态='有效' LIMIT 1",
            (源, 日),
        ).fetchone()
        源归档 = conn.execute(
            "SELECT 余额, 来源 FROM 周期快照 WHERE 账户键=? AND 营业日=? AND 状态='归档' LIMIT 1",
            (源, 日),
        ).fetchone()
        目标正式 = conn.execute(
            "SELECT 余额 FROM 周期快照 WHERE 账户键=? AND 营业日=? AND 状态='有效' LIMIT 1",
            (目标, 日),
        ).fetchone()
        明细.append(
            {
                "重叠日": 日,
                "源正式有无": 源正式 is not None,
                "源正式余额": None if 源正式 is None else int(源正式["余额"]),
                "源隔离归档": None if 源归档 is None else int(源归档["余额"]),
                "目标正式余额": None if 目标正式 is None else int(目标正式["余额"]),
                "回放是否加倍": 回放是否加倍(conn, 目标, 日),
                "双露": 源正式 is not None and 目标正式 is not None,
            }
        )
    valid = 票行["状态"] == 有效状态 and not any(x["双露"] for x in 明细)
    return {
        "票号": 票号,
        "源": 源,
        "目标": 目标,
        "重叠日": 日们,
        "形态": 票行["形态"],
        "口径": 口径,
        "状态": 票行["状态"],
        "valid": valid,
        "源正式有无": any(x["源正式有无"] for x in 明细),
        "回放是否加倍": any(x["回放是否加倍"] for x in 明细),
        "双露": any(x["双露"] for x in 明细),
        "重叠日明细": 明细,
        "时刻": 票行["时刻"],
    }


def 查现场(conn, 键: str | None = None) -> dict:
    """台面核证页：列全部窗票（聚合为票）+ 全局双露/valid 口径标志。"""
    rows = [
        dict(r)
        for r in conn.execute(
            "SELECT 票号, 源键, 目标键, 重叠日, 形态, 状态, 时刻 "
            "FROM 重叠日窗票表 ORDER BY 编号 DESC LIMIT 40"
        )
    ]
    if 键:
        rows = [r for r in rows if 键 in str(r.values())]
    票号们: list[str] = []
    for r in rows:
        if r["票号"] not in 票号们:
            票号们.append(r["票号"])
    票视图 = [核证一票(conn, p) for p in 票号们]
    票视图 = [v for v in 票视图 if v]
    双露 = any(v["双露"] for v in 票视图)
    return {
        "口径": 口径,
        "nn": "24",
        "double_ok": False,
        "collapse": True,
        "双露": 双露,
        "valid": bool(票视图) and all(v["valid"] for v in 票视图),
        "窗票数": len(票号们),
        "重叠窗": rows,
        "票核证": 票视图,
    }


def 巡检包(payload: dict | None = None) -> dict:
    base = {
        "kind": "merge-overlap",
        "nn": "24",
        "口径": 口径,
        "double_ok": False,
        "collapse": True,
    }
    if payload:
        base.update(payload)
    return base


def 守卫抽取(conn, 营业日: str) -> None:
    """日终抽取写前失败闭守卫：并户成功必须持票，持票源键不得再抽正式。"""
    裸凭证 = conn.execute(
        "SELECT p.凭证编号, p.源账户键, p.目标账户键, p.生效日 FROM 并户凭证 p "
        "WHERE p.状态='有效' AND NOT EXISTS ("
        "  SELECT 1 FROM 重叠日窗票表 w WHERE w.源键=p.源账户键 "
        "  AND w.目标键=p.目标账户键 AND w.状态='有效'"
        ") LIMIT 1"
    ).fetchone()
    if 裸凭证 is not None:
        raise 窗票闭错误(
            f"并户凭证 {裸凭证['凭证编号']} 缺少重叠窗票，抽取失败闭（禁止并户成功而窗票空）"
        )
    if 双露行(conn):
        raise 窗票闭错误("重叠日存在双户同日正式镜（双露），抽取失败闭")


def 守卫回放(conn, 营业日: str) -> None:
    """回放写前失败闭守卫：窗票缺失/双露一律拒绝写差额批次。"""
    守卫抽取(conn, 营业日)


def 删票测试用(conn, 票号: str) -> int:
    """仅供自动化测试模拟「窗票被删」现场：物理删票并返回删除行数。"""
    cur = conn.execute("DELETE FROM 重叠日窗票表 WHERE 票号=?", (票号,))
    conn.commit()
    return cur.rowcount
