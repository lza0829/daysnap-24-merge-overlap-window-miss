"""重叠日窗票测试（nn=24）。

全局唯一口径：**以窗票强制坍缩为准**。
两口径可区分点在本口径下断言为：
- 按源键读重叠日正式有效镜：无（仅隔离归档可读）；
- 按目标键余额：只含生效日一次性结转，不含源侧隔离镜逐日复算；
- 回放净额：不加倍（流水改挂目标，源隔离镜不参与）。

硬约束：
- 禁止并户成功而重叠窗票空；
- 禁止重叠日双正式有效镜并存（双露）；
- 并户、日终抽取、流水改挂、快照、回放、账户册同票；
- 并户与抽取抢锁失败闭，不得双正式加倍；
- 删窗票后再抽源必须失败闭。
"""

import importlib
import sys
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

根 = Path(__file__).resolve().parents[1]
if str(根) not in sys.path:
    sys.path.insert(0, str(根))

重载模块 = [
    "app.db",
    "app.seed",
    "app.main",
    "app.services.镜链",
    "app.services.事务",
    "app.services.并户",
    "app.services.并户夹具",
    "app.services.抽取",
    "app.services.回放",
    "app.services.装载",
    "app.modules.重叠日窗票",
    "app.routers.核心",
    "app.routers",
    "app",
]


@pytest.fixture()
def 客(monkeypatch):
    临时 = tempfile.mkdtemp(prefix="daysnap-ov-")
    monkeypatch.setenv("数据目录", 临时)
    monkeypatch.setenv("夹具目录", str(根.parent / "fixtures"))
    for 名 in 重载模块:
        if 名 in sys.modules:
            importlib.reload(sys.modules[名])
    from app.main import app

    with TestClient(app) as c:
        yield c


def _快照(客, 键, 含归档=False):
    参 = f"?账户键={键}" + ("&含归档=true" if 含归档 else "")
    r = 客.get("/api/快照" + 参)
    assert r.status_code == 200, r.text
    return r.json()


def _跑重叠夹具(客):
    r = 客.post("/api/重置业务库")
    assert r.status_code == 200
    r = 客.post("/api/并户夹具", json={"名": "并户重叠窗票样例.json"})
    assert r.status_code == 200, r.text
    return r.json()


# ---------- 甲：源正式空且目标续、回放不加倍 ----------

def test_并户同票开重叠窗_票落库且核证字段齐(客):
    d = _跑重叠夹具(客)
    票 = d["窗票号"]
    assert 票, "并户成功必须同票开重叠窗票"
    r = 客.get(f"/api/核证/重叠日窗/票/{票}")
    assert r.status_code == 200, r.text
    视 = r.json()
    assert 视["票号"] == 票
    assert 视["源"] == "户甲" and 视["目标"] == "户乙"
    assert 视["重叠日"] == ["2026-11-20", "2026-11-21", "2026-11-22"]
    assert 视["口径"] == "窗票强制坍缩"
    assert 视["valid"] is True
    assert 视["源正式有无"] is False
    assert 视["回放是否加倍"] is False
    assert 视["双露"] is False
    assert 客.get("/api/核证/重叠日窗/票/不存在").status_code == 404


def test_强制坍缩_源重叠日正式镜清空_隔离归档可读(客):
    d = _跑重叠夹具(客)
    assert _快照(客, "户甲") == []  # 按源键读正式有效镜为空
    归档 = _快照(客, "户甲", 含归档=True)
    归档日 = {x["营业日"]: x for x in 归档}
    for 日 in ("2026-11-20", "2026-11-21", "2026-11-22"):
        assert 归档日[日]["状态"] == "归档"
        assert 归档日[日]["来源"] == "重叠坍缩归档"
    # 目标接续，重叠日只有目标键一份正式镜
    目标 = {x["营业日"]: x for x in _快照(客, "户乙")}
    for 日 in ("2026-11-20", "2026-11-21", "2026-11-22"):
        assert 日 in 目标 and 目标[日]["状态"] == "有效"


def test_禁止双露_窗票覆盖日无双正式镜(客):
    d = _跑重叠夹具(客)
    现场 = 客.get("/api/核证/重叠日窗").json()
    assert 现场["双露"] is False and 现场["valid"] is True
    assert 现场["double_ok"] is False and 现场["collapse"] is True
    # 直接 SQL 复核：重叠日不存在两户同时有效
    from app.db import 连接
    from app.modules import 重叠日窗票 as 窗票

    conn = 连接()
    try:
        assert 窗票.双露行(conn) == []
    finally:
        conn.close()


def test_回放按目标键_净额不加倍(客):
    d = _跑重叠夹具(客)
    for 回 in d["回放"]:
        assert 回["差额"] == 0 and 回["通过"], 回
        assert 回["回放是否加倍"] is False
    # 生效日目标镜 = 目标前日 + 源末镜一次性结转 + 当日目标净额（改挂流水只算一次）
    目标 = {x["营业日"]: x for x in _快照(客, "户乙")}
    归档 = {x["营业日"]: x for x in _快照(客, "户甲", 含归档=True)}
    乙前 = 目标["2026-11-21"]["余额"]
    甲末 = 归档["2026-11-21"]["余额"]  # 10000
    # 11-22 流水：甲 400（改挂）+ 乙 600 + 乙 300（并后）+ 甲 700（改挂）= 2000
    assert 目标["2026-11-22"]["余额"] == 乙前 + 甲末 + 2000
    # 隔离镜余额不得算进目标键：目标 11-22 不等于 目标值 + 源隔离值
    assert 目标["2026-11-22"]["余额"] != 目标["2026-11-22"]["余额"] + 归档["2026-11-22"]["余额"]


def test_流水改挂同票_源键晚到流水落目标(客):
    d = _跑重叠夹具(客)
    行 = [x for x in 客.get("/api/流水").json() if x["流水号"] == "重-甲-04"]
    assert 行 and 行[0]["账户键"] == "户乙" and 行[0]["原账户键"] == "户甲"


# ---------- 乙：源隔离可读但再抽源拒绝、目标净额不含隔离 ----------

def test_源再抽拒绝_窗票拦抽且不生第二正式镜(客):
    _跑重叠夹具(客)
    r = 客.post("/api/抽取", json={"营业日": "2026-11-22"})
    assert r.status_code == 200
    报 = r.json()
    assert 报["窗票拦抽"] >= 1 and 报["已并户跳过"] >= 1
    assert _快照(客, "户甲") == []  # 再抽源拒绝，无正式镜
    # 目标镜不被盖写改变
    前 = {x["营业日"]: x["余额"] for x in _快照(客, "户乙")}
    客.post("/api/抽取", json={"营业日": "2026-11-22"})
    后 = {x["营业日"]: x["余额"] for x in _快照(客, "户乙")}
    assert 前 == 后


def test_目标净额不含源隔离镜(客):
    _跑重叠夹具(客)
    from app.db import 连接
    from app.services.镜链 import 当日流水净额

    conn = 连接()
    try:
        # 目标键该日净额只统计目标键流水（含改挂），源键已无该日已入账流水
        目标净额 = 当日流水净额(conn, "户乙", "2026-11-22")
        源净额 = 当日流水净额(conn, "户甲", "2026-11-22")
    finally:
        conn.close()
    assert 源净额 == 0
    assert 目标净额 == 2000  # 400+600+300+700，隔离镜 10400 不参与


# ---------- 删窗票：再抽源必须失败闭 ----------

def test_删窗票后抽取回放失败闭(客):
    d = _跑重叠夹具(客)
    from app.db import 连接
    from app.modules import 重叠日窗票 as 窗票

    conn = 连接()
    assert 窗票.删票测试用(conn, d["窗票号"]) >= 1
    conn.close()

    r1 = 客.post("/api/抽取", json={"营业日": "2026-11-22"})
    assert r1.status_code == 400 and "失败闭" in r1.json()["detail"]
    r2 = 客.post("/api/回放", json={"营业日": "2026-11-22"})
    assert r2.status_code == 400 and "失败闭" in r2.json()["detail"]
    # 核证现场标记 invalid（无有效票）
    现场 = 客.get("/api/核证/重叠日窗").json()
    assert 现场["valid"] is False


def test_并户成功不得窗票空_整笔回滚(客):
    """模拟开窗失败：并户必须整笔回滚，不留「成功但无票」现场。"""
    客.post("/api/重置业务库")
    客.post("/api/装载夹具", json={"名": "三日连环样例.json"})
    for 日 in ("2026-11-20", "2026-11-21"):
        客.post("/api/抽取", json={"营业日": 日})
    from app.db import 连接
    from app.modules import 重叠日窗票 as 窗票

    原开 = 窗票.开重叠窗

    def 炸(*a, **k):
        raise 窗票.窗票闭错误("模拟开窗失败")

    窗票.开重叠窗 = 炸
    try:
        r = 客.post(
            "/api/并户",
            json={"源": "户甲", "目标": "户乙", "生效日": "2026-11-22", "凭证编号": "票-回滚-1"},
        )
        assert r.status_code == 400
    finally:
        窗票.开重叠窗 = 原开
    # 账户状态、凭证、窗票均无残留
    户 = {x["账户键"]: x for x in 客.get("/api/账户").json()}
    assert 户["户甲"]["状态"] == "正常" and 户["户甲"]["并户去向"] == ""
    assert 客.get("/api/并户").json() == []
    现场 = 客.get("/api/核证/重叠日窗").json()
    assert 现场["窗票数"] == 0
    # 源正式镜仍在（未被归档）
    assert _快照(客, "户甲") != []


# ---------- 并发：并户与抽取抢锁，不得双正式加倍 ----------

def test_并户与抽取并发_抢锁失败闭_无双正式加倍(客):
    客.post("/api/重置业务库")
    r = 客.post("/api/并户夹具", json={"名": "重叠窗票并发样例.json"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["并发"] is True
    # 两臂都结束（BEGIN IMMEDIATE 串行化），无未捕获崩溃
    assert all(o["完成"] for o in d["并发操作"])
    assert d["双户同日有效镜"] == []
    assert d["重叠双露"] == []
    视 = d["窗票核证"]
    assert 视 and 视["valid"] is True
    assert 视["源正式有无"] is False and 视["回放是否加倍"] is False
    # 源键无正式镜，目标键重叠日唯一一行
    assert _快照(客, "户窗甲") == []
    目标 = [x for x in _快照(客, "户窗乙") if x["营业日"] == "2026-11-22"]
    assert len(目标) == 1
    for 收 in d["收尾回放"]:
        assert 收["差额"] == 0 and 收["通过"] and 收["回放是否加倍"] is False


# ---------- 双露现场：守卫必须失败闭、核证必须标 invalid ----------

def test_双露现场_守卫失败闭_核证invalid(客):
    d = _跑重叠夹具(客)
    from app.db import 连接

    conn = 连接()
    # 人为制造双露：把源户重叠日归档镜重新置为有效（模拟破坏现场）
    conn.execute(
        "UPDATE 周期快照 SET 状态='有效' WHERE 账户键=? AND 营业日=? AND 状态='归档'",
        ("户甲", "2026-11-22"),
    )
    conn.commit()
    conn.close()
    视 = 客.get(f"/api/核证/重叠日窗/票/{d['窗票号']}").json()
    assert 视["双露"] is True and 视["valid"] is False
    assert 视["源正式有无"] is True
    r1 = 客.post("/api/抽取", json={"营业日": "2026-11-22"})
    assert r1.status_code == 400 and "失败闭" in r1.json()["detail"]
    r2 = 客.post("/api/回放", json={"营业日": "2026-11-22"})
    assert r2.status_code == 400 and "失败闭" in r2.json()["detail"]


# ---------- 账户册/总览协同 ----------

def test_账户册与总览暴露窗票协同字段(客):
    _跑重叠夹具(客)
    户 = {x["账户键"]: x for x in 客.get("/api/账户").json()}
    assert 户["户甲"]["状态"] == "已并户"
    assert 户["户甲"]["并户去向"] == "户乙" and 户["户甲"]["并户凭证"] == "凭证-重叠-甲乙"
    总览 = 客.get("/api/总览").json()
    assert 总览["重叠窗票数"] >= 1 and 总览["重叠双露数"] == 0
    台参 = 客.get("/api/台参").json()
    assert 台参["重叠窗票口径"] == "窗票强制坍缩"


def test_无重叠日并户拒绝_不得空窗成功(客):
    """两户镜日严格不相交：并户失败闭，无凭证、无窗票、账户状态不动。

    全量日终抽取会为全部正常账户补镜，故此处手工钉死不相交镜日。
    """
    客.post("/api/重置业务库")
    from app.db import 连接

    conn = 连接()
    conn.execute(
        "INSERT INTO 账户(账户键, 户名, 币种, 开户营业日, 状态) VALUES "
        "('户P','P户','CNY','2026-11-01','正常'),"
        "('户Q','Q户','CNY','2026-11-01','正常')"
    )
    for 键, 日, 额 in (("户P", "2026-11-10", 100), ("户Q", "2026-11-11", 200)):
        conn.execute(
            "INSERT INTO 周期快照(快照键, 账户键, 营业日, 余额, 抽取批次编号, 来源, 状态) "
            "VALUES (?,?,?,?,?,?, '有效')",
            (f"{键}|{日}", 键, 日, 额, "手工", "日终抽取"),
        )
    conn.commit()
    conn.close()
    r = 客.post("/api/并户", json={"源": "户P", "目标": "户Q", "生效日": "2026-11-12"})
    assert r.status_code == 400 and "重叠窗票" in r.json()["detail"]
    户 = {x["账户键"]: x for x in 客.get("/api/账户").json()}
    assert 户["户P"]["状态"] == "正常" and 户["户P"]["并户去向"] == ""
    assert 客.get("/api/并户").json() == []
    assert 客.get("/api/核证/重叠日窗").json()["窗票数"] == 0


def test_两户有镜但镜日不相交_禁开空窗失败闭(客):
    """源、目标均有已公布镜，但从无同营业日镜：窗票集合为空，整笔拒绝回滚。

    用自定义账户把镜日钉死在不相交的两天，避免全量抽取补齐共同镜日。
    """
    客.post("/api/重置业务库")
    from app.db import 连接

    conn = 连接()
    conn.execute(
        "INSERT INTO 账户(账户键, 户名, 币种, 开户营业日, 状态) VALUES "
        "('户X','X户','CNY','2026-11-01','正常'),"
        "('户Y','Y户','CNY','2026-11-01','正常')"
    )
    for 键, 日, 额 in (("户X", "2026-11-10", 100), ("户Y", "2026-11-11", 200)):
        conn.execute(
            "INSERT INTO 周期快照(快照键, 账户键, 营业日, 余额, 抽取批次编号, 来源, 状态) "
            "VALUES (?,?,?,?,?,?, '有效')",
            (f"{键}|{日}", 键, 日, 额, "手工", "日终抽取"),
        )
    conn.commit()
    conn.close()
    r = 客.post("/api/并户", json={"源": "户X", "目标": "户Y", "生效日": "2026-11-12"})
    assert r.status_code == 400 and "重叠窗票" in r.json()["detail"]
    户 = {x["账户键"]: x for x in 客.get("/api/账户").json()}
    assert 户["户X"]["状态"] == "正常"
    assert 客.get("/api/并户").json() == []
    assert 客.get("/api/核证/重叠日窗").json()["窗票数"] == 0
    # 源镜未被归档
    assert [x for x in _快照(客, "户X") if x["营业日"] == "2026-11-10"]
