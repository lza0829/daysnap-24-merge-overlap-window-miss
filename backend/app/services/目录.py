from app.db import 连接


def 总览() -> dict:
    conn = 连接()
    try:
        def 数(sql: str) -> int:
            return int(conn.execute(sql).fetchone()[0])

        return {
            "账户数": 数("SELECT COUNT(*) FROM 账户"),
            "流水数": 数("SELECT COUNT(*) FROM 变动流水 WHERE 命运='已入账'"),
            "快照数": 数("SELECT COUNT(*) FROM 周期快照 WHERE 状态='有效'"),
            "差额行数": 数("SELECT COUNT(*) FROM 差额行 WHERE 状态='有效'"),
            "断档数": 数("SELECT COUNT(*) FROM 断档记录"),
            "跳变数": 数("SELECT COUNT(*) FROM 跳变记录"),
            "旁置数": 数("SELECT COUNT(*) FROM 旁置簿"),
            "并户数": 数("SELECT COUNT(*) FROM 并户凭证 WHERE 状态='有效'"),
            "归档快照数": 数("SELECT COUNT(*) FROM 周期快照 WHERE 状态='归档'"),
            "抽取批次数": 数("SELECT COUNT(*) FROM 抽取批次"),
            "回放批次数": 数("SELECT COUNT(*) FROM 回放批次"),
            "重叠窗票数": 数("SELECT COUNT(DISTINCT 票号) FROM 重叠日窗票表 WHERE 状态='有效'"),
            "重叠双露数": _双露数(conn),
        }
    finally:
        conn.close()


def _双露数(conn) -> int:
    return int(
        conn.execute(
            "SELECT COUNT(*) FROM 重叠日窗票表 w "
            "JOIN 周期快照 s ON s.账户键=w.源键 AND s.营业日=w.重叠日 AND s.状态='有效' "
            "JOIN 周期快照 t ON t.账户键=w.目标键 AND t.营业日=w.重叠日 AND t.状态='有效' "
            "WHERE w.状态='有效'"
        ).fetchone()[0]
    )

def _bf_overview_24() -> dict:
    return {"nn": "24", "proof_linked": False, "gates": []}

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

