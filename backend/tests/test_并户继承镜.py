"""并户继承镜夹具测试：口径为「源键只读归档」。

覆盖：
- 两户有镜后并户，目标续链、源键默认有效镜为空、含归档可见；
- 并户继承只读接口暴露 源/目标/生效日/源键暴露/valid；
- 回放生效日无余额加倍；
- 并户与抽取并发不得出现双户同日有效镜并行累加。
"""

import importlib
import json
import os
import sys
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

根 = Path(__file__).resolve().parents[1]
if str(根) not in sys.path:
    sys.path.insert(0, str(根))


@pytest.fixture()
def 客(monkeypatch):
    临时 = tempfile.mkdtemp(prefix="daysnap-test-")
    monkeypatch.setenv("数据目录", 临时)
    monkeypatch.setenv("夹具目录", str(根.parent / "fixtures"))
    for 名 in [
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
        "app.routers.核心",
        "app.routers",
        "app",
    ]:
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


def test_并户顺序夹具_目标续链_源键归档_无加倍(客):
    r = 客.post("/api/重置业务库")
    assert r.status_code == 200, r.text
    r = 客.post("/api/并户夹具", json={"名": "并户继承样例.json"})
    assert r.status_code == 200, r.text
    结果 = r.json()

    并户 = 结果["并户"]
    assert 并户["源"] == "户甲" and 并户["目标"] == "户乙"
    assert 并户["生效日"] == "2026-11-22"
    assert 并户["改挂流水"] >= 1
    assert 并户["归档快照"] >= 1
    assert 并户["双户同日有效镜"] == 0
    for 项 in 结果["校验"]:
        assert 项["通过"], 项

    
    assert _快照(客, "户甲") == []
    
    归档 = _快照(客, "户甲", 含归档=True)
    assert 归档 and all(x["状态"] == "归档" for x in 归档)

    
    目标 = _快照(客, "户乙")
    日们 = {x["营业日"] for x in 目标}
    assert {"2026-11-22", "2026-11-23"} <= 日们

    
    乙前日 = next(x for x in 目标 if x["营业日"] == "2026-11-21")["余额"]
    甲末 = next(x for x in 归档 if x["营业日"] == "2026-11-21")["余额"]
    乙当日 = next(x for x in 目标 if x["营业日"] == "2026-11-22")["余额"]
    
    assert 乙当日 == 乙前日 + 甲末 + 500 + 300 + 700

    
    for 回 in 结果["回放"]:
        assert 回["差额"] == 0 and 回["通过"], 回


def test_并户继承只读接口(客):
    客.post("/api/重置业务库")
    结果 = 客.post("/api/并户夹具", json={"名": "并户继承样例.json"}).json()
    凭 = 结果["凭证编号"]
    r = 客.get(f"/api/并户/{凭}")
    assert r.status_code == 200, r.text
    视 = r.json()
    assert 视["源"] == "户甲" and 视["目标"] == "户乙"
    assert 视["生效日"] == "2026-11-22"
    assert 视["源键暴露"] is True
    assert 视["valid"] is True
    assert 视["口径"] == "源键只读归档"
    assert 视["目标继承链"]
    assert all(x["状态"] == "有效" for x in 视["目标继承链"])
    assert 视["源归档链"] and all(x["状态"] == "归档" for x in 视["源归档链"])

    assert 客.get("/api/并户/不存在").status_code == 404
    列 = 客.get("/api/并户").json()
    assert any(x["凭证编号"] == 凭 and x["源键暴露"] for x in 列)


def test_源键生效日后禁抽且不产生第二有效镜(客):
    客.post("/api/重置业务库")
    客.post("/api/并户夹具", json={"名": "并户继承样例.json"})
    before = _快照(客, "户甲")
    assert before == []
    
    r = 客.post("/api/抽取", json={"营业日": "2026-11-22"}).json()
    assert r["已并户跳过"] >= 1
    assert _快照(客, "户甲") == []
    assert _快照(客, "户乙")  


def test_并户与抽取并发_无双户同日有效镜(客):
    客.post("/api/重置业务库")
    r = 客.post("/api/并户夹具", json={"名": "并户并发样例.json"})
    assert r.status_code == 200, r.text
    结果 = r.json()
    assert 结果["并发"] is True
    assert 结果["双户同日有效镜"] == []

    
    源有效 = _快照(客, "户并甲")
    assert 源有效 == []
    目标 = _快照(客, "户并乙")
    日22 = [x for x in 目标 if x["营业日"] == "2026-11-22"]
    assert len(日22) == 1

    
    源归档 = _快照(客, "户并甲", 含归档=True)
    甲末 = next(x for x in 源归档 if x["营业日"] == "2026-11-21")["余额"]
    乙前 = next(x for x in 目标 if x["营业日"] == "2026-11-21")["余额"]
    assert 日22[0]["余额"] == 乙前 + 甲末

    for 收 in 结果["收尾回放"]:
        assert 收["差额"] == 0 and 收["通过"], 收


def test_并户拒绝无镜源户_不得只改状态(客):
    客.post("/api/重置业务库")
    r = 客.post("/api/并户", json={"源": "户丙", "目标": "户甲", "生效日": "2026-11-22"})
    assert r.status_code == 400
    assert "无已公布镜" in r.json()["detail"]
    
    户丙 = next(x for x in 客.get("/api/账户").json() if x["账户键"] == "户丙")
    assert 户丙["状态"] == "正常"


def test_并户凭证落库且报告含口径(客):
    客.post("/api/重置业务库")
    结果 = 客.post("/api/并户夹具", json={"名": "并户继承样例.json"}).json()
    凭 = 结果["凭证编号"]
    视 = 客.get(f"/api/并户/{凭}").json()
    assert 视["源末镜日"] == "2026-11-21"
    
    assert 视["源结转余额"] == 10000


def test_生效日盖写不重复结转(客):
    """并户后对生效日重复抽取（盖写）不得把源结转加两次。"""
    客.post("/api/重置业务库")
    结果 = 客.post("/api/并户夹具", json={"名": "并户继承样例.json"}).json()
    凭 = 结果["凭证编号"]
    视 = 客.get(f"/api/并户/{凭}").json()
    目标 = 视["目标"]
    before = {x["营业日"]: x["余额"] for x in 视["目标继承链"]}
    for _ in range(2):
        r = 客.post("/api/抽取", json={"营业日": "2026-11-22"}).json()
        assert r["已并户跳过"] >= 1  
    after = {x["营业日"]: x["余额"] for x in _快照(客, 目标)}
    assert after["2026-11-22"] == before["2026-11-22"]
    
    r = 客.post("/api/回放", json={"营业日": "2026-11-22"}).json()
    assert r["差额"] == 0 and r["通过"], r


def test_并户后源键迟到流水改挂目标且差额可见(客):
    """并户后按源键装载的流水一律改挂目标；落到历史日也不静默丢失。"""
    客.post("/api/重置业务库")
    客.post("/api/并户夹具", json={"名": "并户继承样例.json"})
    r = 客.post(
        "/api/装载",
        json={
            "批次编号": "迟到",
            "流水": [
                {
                    "流水号": "迟-1",
                    "账户键": "户甲",
                    "营业日": "2026-11-20",
                    "发生时": "2026-11-20T23:00:00Z",
                    "变动额": 100,
                    "摘要": "并后迟到",
                }
            ],
        },
    ).json()
    assert r["入账"] == 1
    行 = [x for x in 客.get("/api/流水").json() if x["流水号"] == "迟-1"]
    assert 行 and 行[0]["账户键"] == "户乙" and 行[0]["原账户键"] == "户甲"
    
    回 = 客.post("/api/回放", json={"营业日": "2026-11-20"}).json()
    assert 回["差额"] >= 1
    
    assert _快照(客, "户甲") == []


def test_主链冒烟不回归(客):
    """原主链：三日连环 → 三日抽取 → 回放通过，无差额。"""
    assert 客.post("/api/重置业务库").status_code == 200
    assert 客.post("/api/装载夹具", json={"名": "三日连环样例.json"}).status_code == 200
    for 日 in ("2026-11-20", "2026-11-21", "2026-11-22"):
        assert 客.post("/api/抽取", json={"营业日": 日}).status_code == 200
    r = 客.post("/api/回放", json={"营业日": "2026-11-22"}).json()
    assert r["差额"] == 0 and r["通过"], r
    assert 客.get("/api/并户").json() == []


def test_链式并户_甲到乙再到丙_结转不丢不重(客):
    """甲→乙后乙→丙：丙接续整条链，甲仍只读归档，任何日无双份有效镜。"""
    客.post("/api/重置业务库")
    客.post("/api/装载夹具", json={"名": "三日连环样例.json"})
    for 日 in ("2026-11-20", "2026-11-21"):
        客.post("/api/抽取", json={"营业日": 日})
    一 = 客.post("/api/并户", json={"源": "户甲", "目标": "户乙", "生效日": "2026-11-22"}).json()
    
    客.post("/api/抽取", json={"营业日": "2026-11-22"})
    二 = 客.post("/api/并户", json={"源": "户乙", "目标": "户丙", "生效日": "2026-11-23"}).json()
    客.post("/api/抽取", json={"营业日": "2026-11-23"})

    assert _快照(客, "户甲") == [] and _快照(客, "户乙") == []
    丙 = _快照(客, "户丙")
    日们 = [x["营业日"] for x in 丙]
    assert 日们.count("2026-11-23") == 1

    视二 = 客.get(f"/api/并户/{二['凭证编号']}").json()
    assert 视二["上游源链"] == ["户甲"]
    视一 = 客.get(f"/api/并户/{一['凭证编号']}").json()
    assert 视一["目标当前状态"] == "已并户" and 视一["目标当前承接"] == "户丙"
    
    
    
    assert next(x for x in 丙 if x["营业日"] == "2026-11-23")["余额"] == 22500
    r = 客.post("/api/回放", json={"营业日": "2026-11-23"}).json()
    assert r["差额"] == 0 and r["通过"], r


def test_生效日先抽取后并户_只重算一次不双计(客):
    """目标在生效日已有有效镜时并户：重算必须并入结转一次，不得叠加原值。"""
    客.post("/api/重置业务库")
    客.post("/api/装载夹具", json={"名": "三日连环样例.json"})
    for 日 in ("2026-11-20", "2026-11-21", "2026-11-22"):  
        客.post("/api/抽取", json={"营业日": 日})
    乙前 = next(x for x in _快照(客, "户乙") if x["营业日"] == "2026-11-21")["余额"]
    甲末 = next(x for x in _快照(客, "户甲") if x["营业日"] == "2026-11-21")["余额"]
    r = 客.post("/api/并户", json={"源": "户甲", "目标": "户乙", "生效日": "2026-11-22"}).json()
    
    乙当日 = next(x for x in _快照(客, "户乙") if x["营业日"] == "2026-11-22")["余额"]
    assert 乙当日 == 乙前 + 甲末 + (2000 - 1500)
    assert r["重算目标镜"] and r["重算目标镜"][0]["结转额"] == 甲末
    
    客.post("/api/抽取", json={"营业日": "2026-11-22"})
    assert next(x for x in _快照(客, "户乙") if x["营业日"] == "2026-11-22")["余额"] == 乙当日
    assert 客.post("/api/回放", json={"营业日": "2026-11-22"}).json()["通过"]
