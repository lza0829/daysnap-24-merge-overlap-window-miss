import json
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app import seed
from app.db import 夹具目录, 连接
from app.services import 并户, 并户夹具, 回放, 抽取, 目录, 装载

路由 = APIRouter(prefix="/api")


class 装载请求(BaseModel):
    批次编号: str = ""
    流水: list = Field(default_factory=list)


class 营业日请求(BaseModel):
    营业日: str
    批次编号: str = ""


class 并户请求(BaseModel):
    源: str
    目标: str
    生效日: str
    凭证编号: str = ""


@路由.get("/健康")
def 健康():
    return {
        "正常": True,
        "项目": "日镜账",
        "骨架": "日终余额抽取→周期快照落行→变动流水回放核对→断档跳变检出→快照与回放差额清单",
    }


@路由.get("/总览")
def 取总览():
    return 目录.总览()


@路由.get("/台参")
def 取台参():
    conn = 连接()
    try:
        return {r["键"]: r["值"] for r in conn.execute("SELECT 键, 值 FROM 台参")}
    finally:
        conn.close()


@路由.get("/账户")
def 列账户():
    conn = 连接()
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM 账户 ORDER BY 账户键")]
    finally:
        conn.close()


@路由.get("/流水")
def 列流水(营业日: str = "", 账户键: str = ""):
    conn = 连接()
    try:
        sql = "SELECT * FROM 变动流水 WHERE 1=1"
        args: list = []
        if 营业日:
            sql += " AND 营业日=?"
            args.append(营业日)
        if 账户键:
            sql += " AND 账户键=?"
            args.append(账户键)
        sql += " ORDER BY 营业日 DESC, 发生时 DESC LIMIT 300"
        return [dict(r) for r in conn.execute(sql, args)]
    finally:
        conn.close()


@路由.get("/快照")
def 列快照(营业日: str = "", 账户键: str = "", 含归档: bool = False):
    conn = 连接()
    try:
        if 含归档:
            sql = "SELECT * FROM 周期快照 WHERE 状态 IN ('有效','归档')"
        else:
            sql = "SELECT * FROM 周期快照 WHERE 状态='有效'"
        args: list = []
        if 营业日:
            sql += " AND 营业日=?"
            args.append(营业日)
        if 账户键:
            sql += " AND 账户键=?"
            args.append(账户键)
        sql += " ORDER BY 营业日 DESC, 账户键 LIMIT 300"
        return [dict(r) for r in conn.execute(sql, args)]
    finally:
        conn.close()


@路由.get("/差额")
def 列差额(回放批次编号: str = "", 含失效: bool = False):
    conn = 连接()
    try:
        条件 = "" if 含失效 else " 状态='有效' AND"
        if 回放批次编号:
            rows = conn.execute(
                f"SELECT * FROM 差额行 WHERE{条件} 回放批次编号=? ORDER BY 编号 DESC",
                (回放批次编号,),
            )
        else:
            rows = conn.execute(
                f"SELECT * FROM 差额行 WHERE{条件} 1=1 ORDER BY 编号 DESC LIMIT 200"
            )
        return [dict(r) for r in rows]
    finally:
        conn.close()


@路由.get("/断档")
def 列断档():
    conn = 连接()
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM 断档记录 ORDER BY 编号 DESC LIMIT 200")]
    finally:
        conn.close()


@路由.get("/跳变")
def 列跳变():
    conn = 连接()
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM 跳变记录 ORDER BY 编号 DESC LIMIT 200")]
    finally:
        conn.close()


@路由.get("/旁置")
def 列旁置():
    conn = 连接()
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM 旁置簿 ORDER BY 编号 DESC LIMIT 100")]
    finally:
        conn.close()


def _列批(表: str):
    conn = 连接()
    try:
        out = []
        for r in conn.execute(f"SELECT * FROM {表} ORDER BY 时刻 DESC LIMIT 40"):
            d = dict(r)
            try:
                d["报告"] = json.loads(d.get("报告") or "{}")
            except Exception:
                pass
            out.append(d)
        return out
    finally:
        conn.close()


@路由.get("/装载批次")
def 列装载批():
    return _列批("装载批次")


@路由.get("/抽取批次")
def 列抽取批():
    return _列批("抽取批次")


@路由.get("/回放批次")
def 列回放批():
    return _列批("回放批次")


@路由.get("/夹具")
def 列夹具():
    if not 夹具目录.exists():
        return []
    return sorted(p.name for p in 夹具目录.glob("*.json"))


@路由.post("/装载")
def 执行装载(体: 装载请求):
    try:
        return 装载.装载流水(体.流水, 体.批次编号)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


class 夹具请求(BaseModel):
    名: str


@路由.post("/装载夹具/{name}")
def 装载夹具路径(name: str):
    return _装载夹具文件(name)


@路由.post("/装载夹具")
def 装载夹具体(体: 夹具请求):
    return _装载夹具文件(体.名)


def _装载夹具文件(名: str):
    path = 夹具目录 / 名
    if not path.exists():
        raise HTTPException(404, f"夹具不存在: {名}")
    data = json.loads(path.read_text(encoding="utf-8"))
    流水 = data.get("流水") or data.get("事件") or []
    return 装载.装载流水(流水, str(data.get("批次编号") or ""))


@路由.post("/抽取")
def 执行抽取(体: 营业日请求):
    try:
        return 抽取.日终抽取(体.营业日, 体.批次编号)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@路由.post("/回放")
def 执行回放(体: 营业日请求):
    try:
        return 回放.回放核对(体.营业日, 体.批次编号)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@路由.get("/并户")
def 列并户():
    return 并户.列并户()


@路由.get("/并户/{credential}")
def 取并户继承(credential: str):
    """并户继承只读视图：源、目标、生效日、源键是否暴露、valid。

    Starlette 路径参数名必须是 ASCII 标识符，故此处用 credential。
    """
    out = 并户.并户继承(credential)
    if out is None:
        raise HTTPException(404, f"并户凭证不存在: {credential}")
    return out


@路由.post("/并户")
def 执行并户(体: 并户请求):
    try:
        return 并户.执行并户(体.源, 体.目标, 体.生效日, 体.凭证编号)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


class 并户夹具请求(BaseModel):
    名: str = ""


@路由.post("/并户夹具")
def 执行并户夹具(体: 并户夹具请求):
    try:
        return 并户夹具.执行夹具(体.名)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@路由.post("/重置业务库")
def 重置():
    """开发冒烟用：清业务表并保留账户与台参。"""
    conn = 连接()
    try:
        for t in (
            "变动流水",
            "抽取批次",
            "周期快照",
            "回放批次",
            "差额行",
            "断档记录",
            "跳变记录",
            "旁置簿",
            "装载批次",
            "并户凭证",
            "重叠日窗票表",
        ):
            conn.execute(f"DELETE FROM {t}")
        conn.execute("DELETE FROM 账户")
        seed.写入种子账户(conn)
        conn.commit()
        return {"完成": True, **目录.总览()}
    finally:
        conn.close()

from app.modules import 重叠日窗票 as _bf_mod_24


@路由.get("/核证/重叠日窗")
def 取核证_24(键: str | None = None):
    conn = 连接()
    try:
        return _bf_mod_24.查现场(conn, 键)
    finally:
        conn.close()


@路由.get("/核证/重叠日窗/票/{ticket}")
def 取票核证_24(ticket: str):
    """重叠窗票核证只读接口：票号、重叠日、源正式有无、回放是否加倍、valid。"""
    conn = 连接()
    try:
        视 = _bf_mod_24.核证一票(conn, ticket)
        if 视 is None:
            raise HTTPException(404, f"重叠窗票不存在: {ticket}")
        return 视
    finally:
        conn.close()


@路由.post("/核证/重叠日窗/巡检")
def 巡检核证_24(payload: dict | None = None):
    return _bf_mod_24.巡检包(payload or {})

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

