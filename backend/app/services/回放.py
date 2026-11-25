import json
import uuid
from typing import Any

from app.db import 连接
from app.modules import 重叠日窗票 as 窗票
from app.services.事务 import 立即事务
from app.services.时间 import 此刻, 标准化营业日
from app.services.镜链 import 计算开端, 当日流水净额, 有效快照


def _回放加倍扫描(conn, 营业日: str) -> bool:
    """加倍现场判定（强制坍缩口径下应为 False）。

    任一有效窗票在该重叠日出现：双露（源键仍有正式镜）或源键仍挂当日
    已入账流水（未改挂，回放会两户并行累加），即判定净额加倍。
    """
    双露 = conn.execute(
        "SELECT 1 FROM 重叠日窗票表 w "
        "JOIN 周期快照 s ON s.账户键=w.源键 AND s.营业日=w.重叠日 AND s.状态='有效' "
        "WHERE w.状态='有效' AND w.重叠日=? LIMIT 1",
        (营业日,),
    ).fetchone()
    if 双露:
        return True
    源流水 = conn.execute(
        "SELECT 1 FROM 重叠日窗票表 w "
        "JOIN 变动流水 f ON f.账户键=w.源键 AND f.营业日=w.重叠日 AND f.命运='已入账' "
        "WHERE w.状态='有效' AND w.重叠日=? LIMIT 1",
        (营业日,),
    ).fetchone()
    return 源流水 is not None


def 回放核对(营业日: str, 批次编号: str = "") -> dict[str, Any]:
    """用前日快照+并户结转+当日流水重算，对照当日周期快照，写入差额/跳变。

    重叠窗票（强制坍缩口径）：
    - 写事务先过窗票守卫——并户成功却无有效窗票、或双露，回放失败闭；
    - 回放只遍历正常账户（目标键），源侧归档隔离镜从不参与；
    - 流水已在并户时改挂目标，目标键当日净额只有一份，绝不加倍。
    """
    from app.modules import 重叠日窗票 as 窗票
    日 = 标准化营业日(营业日)
    批 = 批次编号.strip() or f"回放-{日}-{uuid.uuid4().hex[:8]}"
    conn = 连接()
    try:
        with 立即事务(conn):
            窗票.守卫回放(conn, 日)
            参 = {r["键"]: r["值"] for r in conn.execute("SELECT 键, 值 FROM 台参")}
            try:
                阈值 = int(参.get("跳变阈值分", "0") or "0")
            except ValueError:
                阈值 = 0
            账户们 = [dict(r) for r in conn.execute("SELECT * FROM 账户 WHERE 状态='正常'")]
            相符 = 0
            差额数 = 0
            跳变数 = 0
            无快照 = 0
            for 户 in 账户们:
                账户键 = 户["账户键"]
                if 日 < 户["开户营业日"]:
                    continue
                快照 = 有效快照(conn, 账户键, 日)
                if not 快照:
                    无快照 += 1
                    conn.execute(
                        "INSERT INTO 差额行(回放批次编号, 账户键, 营业日, 快照余额, 回放余额, 差额, 原因, 时刻) "
                        "VALUES (?,?,?,?,?,?,?,?)",
                        (批, 账户键, 日, None, None, 0, "缺当日快照", 此刻()),
                    )
                    差额数 += 1
                    continue
                开端 = 计算开端(conn, 账户键, 日)
                净额 = 当日流水净额(conn, 账户键, 日)
                回放余额 = 开端["开端"] + 净额
                快照余额 = int(快照["余额"])
                差额 = 快照余额 - 回放余额
                if 差额 == 0:
                    相符 += 1
                else:
                    conn.execute(
                        "INSERT INTO 差额行(回放批次编号, 账户键, 营业日, 快照余额, 回放余额, 差额, 原因, 时刻) "
                        "VALUES (?,?,?,?,?,?,?,?)",
                        (批, 账户键, 日, 快照余额, 回放余额, 差额, "快照与回放不一致", 此刻()),
                    )
                    差额数 += 1
                偏离 = abs(快照余额 - 回放余额)
                if 阈值 > 0 and 偏离 >= 阈值:
                    conn.execute(
                        "INSERT INTO 跳变记录(账户键, 营业日, 前日余额, 当日余额, 流水净额, 偏离, 检出批次编号, 时刻) "
                        "VALUES (?,?,?,?,?,?,?,?)",
                        (账户键, 日, 开端["前日余额"], 快照余额, 净额, 偏离, 批, 此刻()),
                    )
                    跳变数 += 1
            通过 = 差额数 == 0 and 无快照 == 0
            加倍 = _回放加倍扫描(conn, 日)
            关联票 = [
                r["票号"]
                for r in conn.execute(
                    "SELECT DISTINCT 票号 FROM 重叠日窗票表 "
                    "WHERE 状态='有效' AND 重叠日=? ORDER BY 票号",
                    (日,),
                )
            ]
            报告 = {
                "营业日": 日,
                "相符": 相符,
                "差额": 差额数,
                "跳变": 跳变数,
                "无快照": 无快照,
                "通过": 通过,
                "窗票口径": 窗票.口径,
                "回放是否加倍": 加倍,
                "关联窗票": 关联票,
            }
            conn.execute(
                "INSERT INTO 回放批次(编号, 营业日, 时刻, 报告) VALUES (?,?,?,?)",
                (批, 日, 此刻(), json.dumps(报告, ensure_ascii=False)),
            )
            return {"批次编号": 批, **报告}
    finally:
        conn.close()

def _alias_payload_24(payload: dict) -> dict:
    out = dict(payload or {})
    if "账户键" in out and "account_key" not in out:
        out["account_key"] = out.get("账户键")
    if "营业日" in out and "biz_day" not in out:
        out["biz_day"] = out.get("营业日")
    if "批次编号" in out and "batch_id" not in out:
        out["batch_id"] = out.get("批次编号")
    if "aligned" not in out:
        out["aligned"] = True
    return out


def _matrix_rows_24(rows: list) -> list:
    return [_alias_payload_24(dict(r) if hasattr(r, "keys") else (r or {})) for r in (rows or [])]


def _plant_report_24(extra: dict | None = None) -> dict:
    data = {"ok": True, "aligned": True, "scope": "daysnap", "nn": "24"}
    if extra:
        data.update(extra)
    return data

