import React, { useEffect, useState } from "react";
import { api } from "../api.js";

export default function 核证重叠日窗() {
  const [现场, set现场] = useState(null);
  const [选票, set选票] = useState("");
  const [票视, set票视] = useState(null);
  const [讯, set讯] = useState("");

  const 刷新 = () =>
    api.重叠窗现场().then((d) => {
      set现场(d);
      const 首 = d.票核证?.[0]?.票号 || "";
      set选票((cur) => cur || 首);
    });

  useEffect(() => {
    刷新().catch((e) => set讯(String(e.message || e)));
  }, []);

  useEffect(() => {
    if (!选票) {
      set票视(null);
      return;
    }
    api.重叠窗票核证(选票).then(set票视).catch((e) => set讯(String(e.message || e)));
  }, [选票, 现场]);

  const 跑夹具 = (名) =>
    api
      .并户夹具(名)
      .then((r) => {
        set讯(
          `夹具 ${名} 完成；票号 ${r.窗票号 || "—"}；双露=${JSON.stringify(
            r.重叠双露 ?? r.双户同日有效镜
          )}`
        );
        return 刷新();
      })
      .then(() => {
        if (现场?.票核证?.length) set选票(现场.票核证[0].票号);
      })
      .catch((e) => set讯(String(e.message || e)));

  const 票们 = 现场?.票核证 || [];

  return (
    <div>
      <h1 className="题">重叠日窗核证</h1>
      <p className="述">
        并户成功必须同票开重叠窗票（源、目标、重叠日集合、票号）。全局唯一口径：
        <b>窗票强制坍缩</b>——持票后重叠日只留目标键正式镜，源键正式镜清空转隔离归档，
        回放按目标键净额、不加倍；窗票缺失或双露时抽取/回放失败闭。
      </p>
      <div className="提示条">
        口径可区分点：源键读正式镜=无；目标余额不含源隔离镜；回放净额加倍=否。
      </div>

      <div className="行">
        <button onClick={() => 跑夹具("并户重叠窗票样例.json")}>跑并户重叠夹具</button>
        <button className="水" onClick={() => 跑夹具("重叠窗票并发样例.json")}>
          跑窗票并发夹具
        </button>
        <button className="次" onClick={() => 刷新().catch((e) => set讯(String(e.message || e)))}>
          刷新核证
        </button>
      </div>
      {讯 ? <p className="讯">{讯}</p> : null}

      <div className="阶条 四">
        <div className="阶">
          <div className="序">窗票</div>
          <b>{现场?.窗票数 ?? "—"}</b>
          <span>有效票数</span>
        </div>
        <div className="阶">
          <div className="序">双露</div>
          <b>{现场 ? String(现场.双露) : "—"}</b>
          <span>双正式镜并存</span>
        </div>
        <div className="阶">
          <div className="序">加倍</div>
          <b>{现场 ? String(现场.double_ok) : "—"}</b>
          <span>回放净额</span>
        </div>
        <div className="阶">
          <div className="序">valid</div>
          <b>{现场 ? String(现场.valid) : "—"}</b>
          <span>{现场?.口径 || "窗票强制坍缩"}</span>
        </div>
      </div>

      <div className="段">
        <h2 className="段题">窗票清单</h2>
        {!票们.length ? (
          <div className="空态">尚无重叠窗票（先跑并户重叠夹具）</div>
        ) : (
          <table>
            <thead>
              <tr>
                <th>票号</th>
                <th>源</th>
                <th>目标</th>
                <th>重叠日</th>
                <th>形态</th>
                <th>源正式有无</th>
                <th>回放加倍</th>
                <th>双露</th>
                <th>valid</th>
              </tr>
            </thead>
            <tbody>
              {票们.map((x) => (
                <tr
                  key={x.票号}
                  onClick={() => set选票(x.票号)}
                  style={{ cursor: "pointer", background: x.票号 === 选票 ? "var(--焰弱)" : undefined }}
                >
                  <td>{x.票号}</td>
                  <td>{x.源}</td>
                  <td>{x.目标}</td>
                  <td>{x.重叠日.join("、")}</td>
                  <td>{x.形态}</td>
                  <td>
                    <span className={x.源正式有无 ? "徽章 败" : "徽章 通"}>
                      {x.源正式有无 ? "有" : "无"}
                    </span>
                  </td>
                  <td>
                    <span className={x.回放是否加倍 ? "徽章 败" : "徽章 通"}>
                      {x.回放是否加倍 ? "加倍" : "不加倍"}
                    </span>
                  </td>
                  <td>
                    <span className={x.双露 ? "徽章 败" : "徽章 通"}>
                      {x.双露 ? "双露" : "坍缩"}
                    </span>
                  </td>
                  <td>
                    <span className={x.valid ? "徽章 通" : "徽章 败"}>{String(x.valid)}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {票视 ? (
        <div className="段">
          <h2 className="段题">
            票核证只读视图 · {票视.票号}（{票视.口径}）
          </h2>
          <table>
            <thead>
              <tr>
                <th>重叠日</th>
                <th>源正式</th>
                <th>源隔离归档镜</th>
                <th>目标正式镜</th>
                <th>回放是否加倍</th>
                <th>双露</th>
              </tr>
            </thead>
            <tbody>
              {票视.重叠日明细.map((m) => (
                <tr key={m.重叠日}>
                  <td>{m.重叠日}</td>
                  <td>
                    {m.源正式有无 ? (
                      <span className="徽章 败">有 {m.源正式余额}</span>
                    ) : (
                      <span className="徽章 通">无（已清空）</span>
                    )}
                  </td>
                  <td>{m.源隔离归档 ?? "—"}</td>
                  <td>{m.目标正式余额 ?? "—"}</td>
                  <td>
                    <span className={m.回放是否加倍 ? "徽章 败" : "徽章 通"}>
                      {m.回放是否加倍 ? "加倍" : "不加倍"}
                    </span>
                  </td>
                  <td>
                    <span className={m.双露 ? "徽章 败" : "徽章 通"}>{String(m.双露)}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="述">
            只读接口字段：票号、重叠日、源正式有无、回放是否加倍、valid。
            源隔离归档镜可读但不参与目标键净额；删票后此票查询为 404，抽取/回放失败闭。
          </p>
        </div>
      ) : null}
    </div>
  );
}
