import json
import uuid
from typing import Any

from app.db import 连接
from app.services.事务 import 立即事务
from app.services.时间 import 此刻, 标准化营业日
from app.services.镜链 import 计算开端, 当日流水净额, 前日, 有效快照


def _前归档余额(conn, 账户键: str, 前: str) -> int:
    行 = conn.execute(
        "SELECT 余额 FROM 周期快照 WHERE 账户键=? AND 营业日=? AND 状态 IN ('有效','归档')",
        (账户键, 前),
    ).fetchone()
    return 0 if 行 is None else int(行["余额"])


def _前日(营业日: str) -> str:
    from datetime import date, timedelta

    y, m, d = map(int, 营业日.split("-"))
    return (date(y, m, d) - timedelta(days=1)).isoformat()


def _台参(conn) -> dict[str, str]:
    return {r["键"]: r["值"] for r in conn.execute("SELECT 键, 值 FROM 台参")}


def 日终抽取(营业日: str, 批次编号: str = "") -> dict[str, Any]:
    """按营业日为全部正常账户写周期快照。余额=前日快照(或开户零)+并户结转+当日流水净额。

    并户生效日后源户状态为「已并户」，不再参与抽取；目标户的开端在
    生效日一次性并入源户已公布镜余额，且只并一次。

    重叠窗票（强制坍缩口径）：
    - 写事务先过窗票守卫——并户成功却无有效窗票、或出现双露，抽取失败闭；
    - 已并户源键在生效日后再抽正式镜一律拒绝（窗票.源再抽放行 失败闭），
      仅生效日前的历史归档补写允许落「归档」行，永不写源键正式镜。
    """
    from app.modules import 重叠日窗票 as 窗票
    日 = 标准化营业日(营业日)
    批 = 批次编号.strip() or f"抽取-{日}-{uuid.uuid4().hex[:8]}"
    conn = 连接()
    try:
        with 立即事务(conn):
            窗票.守卫抽取(conn, 日)
            参 = _台参(conn)
            重复 = 参.get("重复抽取", "盖写同日快照")
            缺前日 = 参.get("缺前日策略", "以零为开端")
            账户们 = [
                dict(r)
                for r in conn.execute("SELECT * FROM 账户 WHERE 状态='正常' ORDER BY 账户键")
            ]
            并户源们 = [
                dict(r)
                for r in conn.execute(
                    "SELECT a.*, p.生效日, p.源末镜日 FROM 账户 a "
                    "JOIN 并户凭证 p ON p.源账户键=a.账户键 AND p.状态='有效' "
                    "WHERE a.状态='已并户' ORDER BY a.账户键"
                )
            ]
            源禁抽 = 0
            窗票拦抽 = 0
            for 源 in 并户源们:
                # 失败闭：窗票缺失/失效时不放行任何源键写路径
                if not 窗票.源再抽放行(conn, 源["账户键"], 日):
                    源禁抽 += 1
                    窗票拦抽 += 1
                    continue
                if 日 >= 源["源末镜日"] or 日 < 源["开户营业日"]:
                    源禁抽 += 1
                    continue
                账户们.append({**源, "_归档补写": True})
            已并户跳过 = 源禁抽
            写入 = 0
            盖写 = 0
            旁置 = 0
            断档数 = 0
            结转户 = 0
            归档补写 = 0
            for 户 in 账户们:
                账户键 = 户["账户键"]
                开户日 = 户["开户营业日"]
                if 日 < 开户日:
                    continue
                归档户 = bool(户.get("_归档补写"))
                前 = _前日(日)
                开端 = (
                    {"前日余额": _前归档余额(conn, 账户键, 前), "结转额": 0, "开端": _前归档余额(conn, 账户键, 前)}
                    if 归档户
                    else 计算开端(conn, 账户键, 日)
                )
                if not 归档户 and 开端["结转额"]:
                    结转户 += 1
                if (
                    not 归档户
                    and 有效快照(conn, 账户键, 前) is None
                    and 开端["结转额"] == 0
                ):
                    if 日 == 开户日 or 缺前日 == "以零为开端":
                        pass
                    else:
                        conn.execute(
                            "INSERT INTO 断档记录(账户键, 缺营业日, 检出批次编号, 处置, 时刻) VALUES (?,?,?,?,?)",
                            (账户键, 前, 批, "记断档并继续", 此刻()),
                        )
                        断档数 += 1
                净额 = 当日流水净额(conn, 账户键, 日)
                余额 = 开端["开端"] + 净额
                if 归档户:
                    旧 = conn.execute(
                        "SELECT 快照键 FROM 周期快照 WHERE 账户键=? AND 营业日=?",
                        (账户键, 日),
                    ).fetchone()
                    if 旧:
                        旁置 += 1
                        continue
                    conn.execute(
                        "INSERT INTO 周期快照(快照键, 账户键, 营业日, 余额, 抽取批次编号, 来源, 状态) "
                        "VALUES (?,?,?,?,?,?,?)",
                        (f"{账户键}|{日}", 账户键, 日, 余额, 批, "并户归档补写", "归档"),
                    )
                    归档补写 += 1
                    continue
                快照键 = f"{账户键}|{日}"
                旧 = conn.execute(
                    "SELECT 快照键 FROM 周期快照 WHERE 账户键=? AND 营业日=?",
                    (账户键, 日),
                ).fetchone()
                if 旧:
                    if 重复 != "盖写同日快照":
                        conn.execute(
                            "INSERT INTO 旁置簿(原因, 账户键, 营业日, 载荷, 时刻) VALUES (?,?,?,?,?)",
                            (
                                "同日已有快照",
                                账户键,
                                日,
                                json.dumps({"余额": 余额}, ensure_ascii=False),
                                此刻(),
                            ),
                        )
                        旁置 += 1
                        continue
                    conn.execute(
                        "UPDATE 周期快照 SET 余额=?, 抽取批次编号=?, 来源='日终抽取', 状态='有效' "
                        "WHERE 账户键=? AND 营业日=?",
                        (余额, 批, 账户键, 日),
                    )
                    盖写 += 1
                else:
                    conn.execute(
                        "INSERT INTO 周期快照(快照键, 账户键, 营业日, 余额, 抽取批次编号, 来源, 状态) "
                        "VALUES (?,?,?,?,?,?,?)",
                        (快照键, 账户键, 日, 余额, 批, "日终抽取", "有效"),
                    )
                    写入 += 1
            报告 = {
                "营业日": 日,
                "写入": 写入,
                "盖写": 盖写,
                "旁置": 旁置,
                "断档": 断档数,
                "并户结转户": 结转户,
                "归档补写": 归档补写,
                "已并户跳过": 已并户跳过,
                "窗票拦抽": 窗票拦抽,
                "账户扫描": len(账户们),
                "关联窗票": [
                    r["票号"]
                    for r in conn.execute(
                        "SELECT DISTINCT 票号 FROM 重叠日窗票表 "
                        "WHERE 状态='有效' AND 重叠日=? ORDER BY 票号",
                        (日,),
                    )
                ],
                "窗票口径": 窗票.口径,
            }
            conn.execute(
                "INSERT INTO 抽取批次(编号, 营业日, 时刻, 报告) VALUES (?,?,?,?)",
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

