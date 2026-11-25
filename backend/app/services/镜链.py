"""并户镜像链公共计算：前日镜 + 并户结转，供抽取与回放共用。

口径：源键只读归档。
- 源户历史快照全部置为「归档」，按源键默认查询（仅有效）为空；
- 目标户接续源户已公布镜链条，结转额在生效日一次性并入目标开端；
- 结转只加一次：若目标户在 [生效日, 当日) 已有有效镜，说明链条已接上。
"""

from datetime import date, timedelta


def 前日(营业日: str) -> str:
    y, m, d = map(int, 营业日.split("-"))
    return (date(y, m, d) - timedelta(days=1)).isoformat()


def 有效快照(conn, 账户键: str, 营业日: str):
    return conn.execute(
        "SELECT * FROM 周期快照 WHERE 账户键=? AND 营业日=? AND 状态='有效'",
        (账户键, 营业日),
    ).fetchone()


def 生效结转项(conn, 目标键: str, 营业日: str) -> list:
    """目标键在营业日的并户结转明细。每个源户至多加一次。"""
    rows = conn.execute(
        "SELECT 凭证编号, 源账户键, 生效日, 源末镜日, 源结转余额 FROM 并户凭证 "
        "WHERE 目标账户键=? AND 状态='有效' AND 生效日<=? "
        "AND NOT EXISTS ("
        "  SELECT 1 FROM 周期快照 s WHERE s.账户键=并户凭证.目标账户键 "
        "  AND s.状态='有效' AND s.营业日>=并户凭证.生效日 AND s.营业日<?"
        ") ORDER BY 生效日, 凭证编号",
        (目标键, 营业日, 营业日),
    ).fetchall()
    return [dict(r) for r in rows]


def 计算开端(conn, 账户键: str, 营业日: str) -> dict:
    """开端 = 前日有效镜余额 + 尚未并入的并户结转额。"""
    前日快照 = 有效快照(conn, 账户键, 前日(营业日))
    前日余额 = 0 if 前日快照 is None else int(前日快照["余额"])
    结转 = 生效结转项(conn, 账户键, 营业日)
    结转额 = sum(int(r["源结转余额"]) for r in 结转)
    return {
        "前日余额": 前日余额,
        "结转额": 结转额,
        "结转明细": 结转,
        "开端": 前日余额 + 结转额,
    }


def 当日流水净额(conn, 账户键: str, 营业日: str) -> int:
    return int(
        conn.execute(
            "SELECT COALESCE(SUM(变动额),0) AS s FROM 变动流水 "
            "WHERE 账户键=? AND 营业日=? AND 命运='已入账'",
            (账户键, 营业日),
        ).fetchone()["s"]
    )
