"""并户继承镜写路径与只读查询。

硬约束：
- 禁止只改账户状态：并户必须在同一事务内归档源户快照、改挂流水、
  重算目标户生效日及以后的快照、清理失效差额行；
- 半截不得双户同日有效镜：源户生效日起不得再有有效镜，并户后默认
  按源键列有效镜必须为空；
- 口径为「源键只读归档」：源键历史行保留可读但状态为「归档」，
  凭证记录 源键暴露=True，生效日后禁止对源户抽取。
"""

import json
import uuid
from typing import Any

from app.db import 连接
from app.services.事务 import 立即事务
from app.services.时间 import 此刻, 标准化营业日
from app.services.镜链 import 计算开端, 当日流水净额, 前日, 有效快照

执行口径 = "源键只读归档"


def _校验账户(conn, 源: str, 目标: str, 生效日: str) -> tuple[dict, dict]:
    if not 源 or not 目标:
        raise ValueError("源账户键与目标账户键均不能为空")
    if 源 == 目标:
        raise ValueError("源账户与目标账户不能相同")
    源户 = conn.execute("SELECT * FROM 账户 WHERE 账户键=?", (源,)).fetchone()
    目标户 = conn.execute("SELECT * FROM 账户 WHERE 账户键=?", (目标,)).fetchone()
    if not 源户:
        raise ValueError(f"源账户不存在: {源}")
    if not 目标户:
        raise ValueError(f"目标账户不存在: {目标}")
    if 源户["状态"] != "正常":
        raise ValueError(f"源账户状态为「{源户['状态']}」，不可并户")
    if 目标户["状态"] != "正常":
        raise ValueError(f"目标账户状态为「{目标户['状态']}」，不可承接并户")
    已有 = conn.execute(
        "SELECT 凭证编号 FROM 并户凭证 WHERE 源账户键=? AND 状态='有效'", (源,)
    ).fetchone()
    if 已有:
        raise ValueError(f"源账户已并户，凭证: {已有['凭证编号']}")
    
    
    if 生效日 < 源户["开户营业日"] or 生效日 < 目标户["开户营业日"]:
        raise ValueError("并户生效日不得早于任一账户的开户营业日")
    return dict(源户), dict(目标户)


def _源末镜(conn, 源: str, 生效日: str):
    行 = conn.execute(
        "SELECT 余额, 营业日 FROM 周期快照 WHERE 账户键=? AND 状态='有效' AND 营业日<? "
        "ORDER BY 营业日 DESC LIMIT 1",
        (源, 生效日),
    ).fetchone()
    return 行


def _链上目标(conn, 账户键: str) -> list[str]:
    """沿凭证边追溯某账户的上游源户（审计展示用）。"""
    链: list[str] = []
    当前 = 账户键
    已访: set[str] = set()
    while 当前 not in 已访:
        已访.add(当前)
        凭 = conn.execute(
            "SELECT 源账户键 FROM 并户凭证 WHERE 目标账户键=? AND 状态='有效' "
            "ORDER BY 生效日, 凭证编号 LIMIT 1",
            (当前,),
        ).fetchone()
        if 凭 is None:
            break
        当前 = 凭["源账户键"]
        链.append(当前)
    return 链


def _重算目标镜(conn, 目标: str, 生效日: str) -> list[dict]:
    """按升序重算目标户生效日及以后的有效镜，保证结转只并入一次。"""
    日们 = [
        r["营业日"]
        for r in conn.execute(
            "SELECT 营业日 FROM 周期快照 WHERE 账户键=? AND 状态='有效' AND 营业日>=? "
            "ORDER BY 营业日",
            (目标, 生效日),
        )
    ]
    重算 = []
    for 日 in 日们:
        开端 = 计算开端(conn, 目标, 日)
        净额 = 当日流水净额(conn, 目标, 日)
        余额 = 开端["开端"] + 净额
        conn.execute(
            "UPDATE 周期快照 SET 余额=? WHERE 账户键=? AND 营业日=? AND 状态='有效'",
            (余额, 目标, 日),
        )
        重算.append(
            {
                "营业日": 日,
                "前日余额": 开端["前日余额"],
                "结转额": 开端["结转额"],
                "流水净额": 净额,
                "余额": 余额,
            }
        )
    return 重算


def _断言无双户同日有效镜(conn, 源: str, 目标: str, 生效日: str) -> None:
    双户 = conn.execute(
        "SELECT s.营业日 FROM 周期快照 s JOIN 周期快照 t "
        "ON s.营业日=t.营业日 AND t.账户键=? "
        "WHERE s.账户键=? AND s.状态='有效' AND t.状态='有效' AND s.营业日>=? LIMIT 1",
        (目标, 源, 生效日),
    ).fetchone()
    if 双户:
        raise ValueError(f"并户后仍存在双户同日有效镜: {双户['营业日']}")
    残留 = conn.execute(
        "SELECT 营业日 FROM 周期快照 WHERE 账户键=? AND 状态='有效' AND 营业日>=? LIMIT 1",
        (源, 生效日),
    ).fetchone()
    if 残留:
        raise ValueError(f"源户生效日后仍有有效镜: {残留['营业日']}")


def 执行并户(源: str, 目标: str, 生效日: str, 凭证编号: str = "") -> dict[str, Any]:
    源 = (源 or "").strip()
    目标 = (目标 or "").strip()
    日 = 标准化营业日(生效日)
    凭 = 凭证编号.strip() or f"并户-{源}-{目标}-{uuid.uuid4().hex[:8]}"
    conn = 连接()
    try:
        with 立即事务(conn):
            源户, 目标户 = _校验账户(conn, 源, 目标, 日)

            源末 = _源末镜(conn, 源, 日)
            目标末 = _源末镜(conn, 目标, 日)
            if 源末 is None:
                raise ValueError("源户无已公布镜，禁止只改状态不迁镜")
            if 目标末 is None:
                raise ValueError("目标户无已公布镜，并户前须两户均有镜")

            结转余额 = int(源末["余额"])
            源末镜日 = 源末["营业日"]

            
            归档 = conn.execute(
                "UPDATE 周期快照 SET 状态='归档', "
                "来源=CASE WHEN 营业日>=? THEN '并户归档' ELSE 来源 END "
                "WHERE 账户键=? AND 状态='有效'",
                (日, 源),
            ).rowcount
            生效日残留 = conn.execute(
                "SELECT COUNT(*) AS c FROM 周期快照 WHERE 账户键=? AND 状态='归档' "
                "AND 营业日>=? AND 来源='并户归档'",
                (源, 日),
            ).fetchone()["c"]

            
            改挂 = conn.execute(
                "UPDATE 变动流水 SET 原账户键=账户键, 账户键=? "
                "WHERE 账户键=? AND 营业日>=?",
                (目标, 源, 日),
            ).rowcount

            
            conn.execute(
                "UPDATE 账户 SET 状态='已并户', 并户去向=?, 并户凭证=? WHERE 账户键=?",
                (目标, 凭, 源),
            )

            
            差额失效 = conn.execute(
                "UPDATE 差额行 SET 状态='已失效' "
                "WHERE 账户键 IN (?,?) AND 营业日>=? AND 状态='有效'",
                (源, 目标, 日),
            ).rowcount

            
            conn.execute(
                "INSERT INTO 并户凭证(凭证编号, 源账户键, 目标账户键, 生效日, 源末镜日, "
                "源结转余额, 源键暴露, 状态, 报告, 时刻) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (凭, 源, 目标, 日, 源末镜日, 结转余额, 1, "有效", "{}", 此刻()),
            )

            重算 = _重算目标镜(conn, 目标, 日)
            _断言无双户同日有效镜(conn, 源, 目标, 日)

            报告 = {
                "口径": 执行口径,
                "源": 源,
                "目标": 目标,
                "生效日": 日,
                "源末镜日": 源末镜日,
                "源结转余额": 结转余额,
                "源键暴露": True,
                "归档快照": 归档,
                "生效日残留归档": 生效日残留,
                "改挂流水": 改挂,
                "差额置失效": 差额失效,
                "重算目标镜": 重算,
                "双户同日有效镜": 0,
            }
            conn.execute(
                "UPDATE 并户凭证 SET 报告=? WHERE 凭证编号=?",
                (json.dumps(报告, ensure_ascii=False), 凭),
            )
        return {"凭证编号": 凭, **报告}
    finally:
        conn.close()


def 承接账户(conn, 账户键: str) -> str | None:
    """已并户账户的承接目标；正常账户返回自身；无有效凭证返回 None。"""
    当前 = 账户键
    已访: set[str] = set()
    while 当前 not in 已访:
        已访.add(当前)
        凭 = conn.execute(
            "SELECT 目标账户键 FROM 并户凭证 WHERE 源账户键=? AND 状态='有效' "
            "ORDER BY 生效日 DESC, 凭证编号 DESC LIMIT 1",
            (当前,),
        ).fetchone()
        if 凭 is None:
            return 当前
        当前 = 凭["目标账户键"]
    return None


def 列并户() -> list[dict]:
    conn = 连接()
    try:
        out = []
        for r in conn.execute("SELECT * FROM 并户凭证 ORDER BY 时刻 DESC, 凭证编号"):
            d = dict(r)
            d["源键暴露"] = bool(d.get("源键暴露"))
            d["valid"] = d.get("状态") == "有效"
            try:
                d["报告"] = json.loads(d.get("报告") or "{}")
            except Exception:
                pass
            out.append(d)
        return out
    finally:
        conn.close()


def 取并户(凭证编号: str) -> dict | None:
    for d in 列并户():
        if d["凭证编号"] == 凭证编号:
            return d
    return None


def 并户继承(凭证编号: str) -> dict | None:
    """并户继承只读视图：源、目标、生效日、源键是否暴露、valid。"""
    凭 = 取并户(凭证编号)
    if 凭 is None:
        return None
    conn = 连接()
    try:
        目标链 = [
            {k: r[k] for k in ("营业日", "余额", "来源", "状态")}
            for r in conn.execute(
                "SELECT 营业日, 余额, 来源, 状态 FROM 周期快照 "
                "WHERE 账户键=? AND 营业日>=? ORDER BY 营业日",
                (凭["目标账户键"], 凭["生效日"]),
            )
        ]
        源归档 = [
            {k: r[k] for k in ("营业日", "余额", "来源", "状态")}
            for r in conn.execute(
                "SELECT 营业日, 余额, 来源, 状态 FROM 周期快照 "
                "WHERE 账户键=? AND 状态='归档' ORDER BY 营业日",
                (凭["源账户键"],),
            )
        ]
        目标户 = conn.execute(
            "SELECT 状态, 并户去向 FROM 账户 WHERE 账户键=?", (凭["目标账户键"],)
        ).fetchone()
        return {
            "凭证编号": 凭["凭证编号"],
            "源": 凭["源账户键"],
            "目标": 凭["目标账户键"],
            "生效日": 凭["生效日"],
            "源键暴露": 凭["源键暴露"],
            "valid": 凭["valid"],
            "目标当前状态": 目标户["状态"] if 目标户 else "未知",
            "目标当前承接": (目标户["并户去向"] if 目标户 else "") or "",
            "上游源链": _链上目标(conn, 凭["源账户键"]),
            "状态": 凭["状态"],
            "口径": 执行口径,
            "源末镜日": 凭["源末镜日"],
            "源结转余额": 凭["源结转余额"],
            "目标继承链": 目标链,
            "源归档链": 源归档,
        }
    finally:
        conn.close()
