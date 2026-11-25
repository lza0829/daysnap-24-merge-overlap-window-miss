状态 = "半截"


def 源正式应清空(conn, 源键: str, 日: str) -> bool:
    return False


def 回放是否加倍(conn, 目标键: str, 日: str) -> bool:
    return True


def 开重叠窗(conn, **kwargs) -> str:
    return ""


def 源再抽放行(conn, 源键: str) -> bool:
    return True

def 表名() -> str:
    return "重叠日窗票表"


def 查现场(conn, 键: str | None = None) -> dict:
    rows = []
    try:
        rows = [dict(r) for r in conn.execute(
            "SELECT 票号, 源键, 目标键, 重叠日, 形态, 状态 FROM 重叠日窗票表 ORDER BY 编号 DESC LIMIT 40"
        )]
    except Exception:
        rows = []
    if 键:
        rows = [r for r in rows if 键 in str(r.values())]
    return {"重叠窗": rows, "双露": True, "nn": "24", "valid": False}


def 巡检包(payload: dict | None = None) -> dict:
    base = {"kind": "merge-overlap", "nn": "24", "double_ok": True, "collapse": False}
    if payload:
        base.update(payload)
    return base
