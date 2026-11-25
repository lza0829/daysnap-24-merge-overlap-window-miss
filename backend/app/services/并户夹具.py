"""并户夹具执行器：顺序夹具与并发夹具。

顺序夹具（默认）：
  流水 → 预抽取 → 并户 → 并户后流水 → 后抽取 → 回放

并发夹具（"并发": true）：
  预抽取完成后，将「并发操作」同时发起（并户 / 抽取），用线程与
  BEGIN IMMEDIATE 写事务串行化，结束后校验不得出现双户同日有效镜。
"""

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from app.db import 夹具目录, 连接
from app.modules import 重叠日窗票 as 窗票
from app.services import 并户 as 并户服务
from app.services import 回放, 抽取, 装载
from app.services.时间 import 标准化营业日
from app.services.镜链 import 有效快照

默认夹具 = "并户继承样例.json"
重叠夹具 = "并户重叠窗票样例.json"


def _读(名: str) -> dict:
    path = 夹具目录 / (名 or 默认夹具)
    if not path.exists():
        raise ValueError(f"夹具不存在: {名}")
    return json.loads(path.read_text(encoding="utf-8"))


def _并发执行(操作们: list[dict]) -> list[dict]:
    门 = threading.Barrier(len(操作们))
    结果: list[dict | None] = [None] * len(操作们)

    def 跑(i: int, 操作: dict):
        门.wait()
        try:
            if 操作["类型"] == "并户":
                r = 并户服务.执行并户(
                    操作["源"],
                    操作["目标"],
                    str(操作["生效日"]),
                    str(操作.get("凭证编号") or ""),
                )
            elif 操作["类型"] == "抽取":
                r = 抽取.日终抽取(str(操作["营业日"]), str(操作.get("批次编号") or ""))
            elif 操作["类型"] == "回放":
                r = 回放.回放核对(str(操作["营业日"]), str(操作.get("批次编号") or ""))
            else:
                raise ValueError(f"未知并发操作: {操作.get('类型')}")
            结果[i] = {"操作": 操作, "完成": True, "结果": r}
        except Exception as e:  
            结果[i] = {"操作": 操作, "完成": False, "错误": str(e)}

    with ThreadPoolExecutor(max_workers=len(操作们)) as 池:
        for i, 操作 in enumerate(操作们):
            池.submit(跑, i, 操作)
    return [r for r in 结果 if r is not None]


def _双户同日有效镜(源: str, 目标: str, 生效日: str) -> list[dict]:
    conn = 连接()
    try:
        rows = conn.execute(
            "SELECT s.账户键 AS 源键, t.账户键 AS 目标键, s.营业日, s.余额 AS 源余额, "
            "t.余额 AS 目标余额 FROM 周期快照 s JOIN 周期快照 t "
            "ON s.营业日=t.营业日 AND t.账户键=? "
            "WHERE s.账户键=? AND s.状态='有效' AND t.状态='有效' AND s.营业日>=? "
            "ORDER BY s.营业日",
            (目标, 源, 生效日),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _抽取汇总(结果: dict) -> dict:
    return {
        "批次编号": 结果.get("批次编号"),
        "写入": 结果.get("写入", 0),
        "盖写": 结果.get("盖写", 0),
        "旁置": 结果.get("旁置", 0),
        "断档": 结果.get("断档", 0),
        "并户结转户": 结果.get("并户结转户", 0),
        "已并户跳过": 结果.get("已并户跳过", 0),
    }


def _落账户(账户们: list[dict]) -> int:
    if not 账户们:
        return 0
    conn = 连接()
    try:
        for 户 in 账户们:
            conn.execute(
                "INSERT INTO 账户(账户键, 户名, 币种, 开户营业日, 状态) VALUES (?,?,?,?,?) "
                "ON CONFLICT(账户键) DO UPDATE SET 户名=excluded.户名, "
                "币种=excluded.币种, 开户营业日=excluded.开户营业日",
                (
                    str(户["账户键"]),
                    str(户.get("户名") or 户["账户键"]),
                    str(户.get("币种") or "CNY"),
                    str(户["开户营业日"]),
                    "正常",
                ),
            )
        conn.commit()
        return len(账户们)
    finally:
        conn.close()


def 执行夹具(名: str = "") -> dict[str, Any]:
    数据 = _读(名)
    名 = 名 or 默认夹具
    账户落 = _落账户(数据.get("账户") or [])
    流水 = 数据.get("流水") or []
    装载结果 = 装载.装载流水(流水, str(数据.get("批次编号") or "")) if 流水 else None

    预抽取 = [_抽取汇总(抽取.日终抽取(日)) for 日 in 数据.get("预抽取", [])]
    并发 = bool(数据.get("并发"))

    if 并发:
        并发结果 = _并发执行(数据.get("并发操作") or [])
        收尾抽取 = [_抽取汇总(抽取.日终抽取(日)) for 日 in 数据.get("收尾抽取", [])]
        收尾回放 = [回放.回放核对(日) for 日 in 数据.get("收尾回放", [])]
        并户声明 = next((o for o in 数据.get("并发操作") or [] if o.get("类型") == "并户"), None)
        凭证 = ""
        票号 = ""
        if 并户声明:
            凭证 = str(并户声明.get("凭证编号") or "")
            if not 凭证:
                for r in 并发结果:
                    if r["完成"] and r["操作"].get("类型") == "并户":
                        凭证 = str(r["结果"].get("凭证编号") or "")
        if 并户声明:
            票号 = _并户票号(并户声明["源"], 并户声明["目标"])
        窗核证 = _窗票核证视图(票号) if 票号 else None
        return {
            "夹具": 名,
            "并发": True,
            "账户落": 账户落,
            "装载": 装载结果,
            "预抽取": 预抽取,
            "并发操作": 并发结果,
            "收尾抽取": 收尾抽取,
            "收尾回放": 收尾回放,
            "凭证编号": 凭证,
            "窗票号": 票号,
            "窗票核证": 窗核证,
            "双户同日有效镜": (
                _双户同日有效镜(
                    并户声明["源"], 并户声明["目标"], 标准化营业日(并户声明["生效日"])
                )
                if 并户声明
                else []
            ),
            "重叠双露": _全局双露() if 票号 else [],
        }

    并户声明 = 数据.get("并户") or {}
    并户结果 = None
    if 并户声明:
        并户结果 = 并户服务.执行并户(
            并户声明["源"],
            并户声明["目标"],
            str(并户声明["生效日"]),
            str(并户声明.get("凭证编号") or ""),
        )

    后流水 = 数据.get("并户后流水") or []
    后装载 = 装载.装载流水(后流水, str(数据.get("后批次编号") or "")) if 后流水 else None
    后抽取 = [_抽取汇总(抽取.日终抽取(日)) for 日 in 数据.get("后抽取", [])]
    回放们 = [回放.回放核对(日) for 日 in 数据.get("回放", [])]

    校验 = []
    if 并户结果:
        源, 目标, 日 = 并户结果["源"], 并户结果["目标"], 并户结果["生效日"]
        凭证 = 并户结果["凭证编号"]
        校验.append({"项": "源键默认有效镜为空", "值": _源有效(源), "通过": _源有效(源) == 0})
        校验.append(
            {"项": "源键归档只读行数", "值": _源归档(源), "通过": _源归档(源) > 0}
        )
        双户 = _双户同日有效镜(源, 目标, 日)
        校验.append({"项": "无双户同日有效镜", "值": 双户, "通过": 双户 == []})
        继承 = 并户服务.并户继承(凭证)
        校验.append(
            {
                "项": "凭证源键暴露",
                "值": 继承 and 继承["源键暴露"],
                "通过": bool(继承 and 继承["源键暴露"] is True and 继承["valid"]),
            }
        )
        校验.append(
            {
                "项": "并户后回放无差额",
                "值": [{"营业日": r["营业日"], "差额": r["差额"], "通过": r["通过"]} for r in 回放们],
                "通过": all(r["差额"] == 0 and r["通过"] for r in 回放们),
            }
        )
        生效日余额 = _回放同日目标余额(目标, 日)
        校验.append(
            {
                "项": "回放生效日无加倍",
                "值": 生效日余额,
                "通过": 生效日余额 is not None,
            }
        )
        票号 = str(并户结果.get("窗票号") or "")
        窗核证 = _窗票核证视图(票号) if 票号 else None
        校验.append(
            {
                "项": "并户成功同票开重叠窗票",
                "值": 票号,
                "通过": bool(票号 and 窗核证 and 窗核证["valid"]),
            }
        )
        校验.append(
            {
                "项": "重叠窗票禁止双露",
                "值": _全局双露(),
                "通过": _全局双露() == [],
            }
        )
        if 窗核证:
            校验.append(
                {
                    "项": "重叠日源正式镜清空",
                    "值": 窗核证["源正式有无"],
                    "通过": 窗核证["源正式有无"] is False,
                }
            )
            校验.append(
                {
                    "项": "回放净额不加倍",
                    "值": 窗核证["回放是否加倍"],
                    "通过": 窗核证["回放是否加倍"] is False,
                }
            )
    else:
        凭证 = ""
        票号 = ""
        窗核证 = None

    return {
        "夹具": 名,
        "并发": False,
        "账户落": 账户落,
        "装载": 装载结果,
        "预抽取": 预抽取,
        "并户": 并户结果,
        "并户后装载": 后装载,
        "后抽取": 后抽取,
        "回放": 回放们,
        "凭证编号": 凭证,
        "窗票号": 票号,
        "窗票核证": 窗核证,
        "校验": 校验,
    }


def _回放同日目标余额(目标: str, 生效日: str) -> int | None:
    """生效日目标镜应等于 目标前日 + 源结转 + 当日净额；不等即加倍或漏加。"""
    conn = 连接()
    try:
        from app.services.镜链 import 计算开端, 当日流水净额, 前日, 有效快照

        前 = 前日(生效日)
        快照 = 有效快照(conn, 目标, 生效日)
        前日镜 = 有效快照(conn, 目标, 前)
        if 快照 is None or 前日镜 is None:
            return None
        结转 = 计算开端(conn, 目标, 生效日)["结转额"]
        期望 = int(前日镜["余额"]) + 结转 + 当日流水净额(conn, 目标, 生效日)
        return int(快照["余额"]) if int(快照["余额"]) == 期望 else None
    finally:
        conn.close()


def _源有效(源: str) -> int:
    conn = 连接()
    try:
        return int(
            conn.execute(
                "SELECT COUNT(*) AS c FROM 周期快照 WHERE 账户键=? AND 状态='有效'", (源,)
            ).fetchone()["c"]
        )
    finally:
        conn.close()


def _源归档(源: str) -> int:
    conn = 连接()
    try:
        return int(
            conn.execute(
                "SELECT COUNT(*) AS c FROM 周期快照 WHERE 账户键=? AND 状态='归档'", (源,)
            ).fetchone()["c"]
        )
    finally:
        conn.close()


def _并户票号(源: str, 目标: str) -> str:
    conn = 连接()
    try:
        row = conn.execute(
            "SELECT 票号 FROM 重叠日窗票表 WHERE 源键=? AND 目标键=? AND 状态='有效' "
            "ORDER BY 编号 DESC LIMIT 1",
            (源, 目标),
        ).fetchone()
        return row["票号"] if row else ""
    finally:
        conn.close()


def _窗票核证视图(票号: str) -> dict | None:
    if not 票号:
        return None
    conn = 连接()
    try:
        return 窗票.核证一票(conn, 票号)
    finally:
        conn.close()


def _全局双露() -> list[dict]:
    conn = 连接()
    try:
        return 窗票.双露行(conn)
    finally:
        conn.close()
