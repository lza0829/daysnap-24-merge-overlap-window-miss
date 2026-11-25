import React, { useEffect, useState } from "react";
import { api } from "../api.js";

export default function 差额清单() {
  const [行, set行] = useState([]);
  const [含失效, set含失效] = useState(false);
  const [讯, set讯] = useState("");
  const 刷新 = () => api.差额(含失效 ? "?含失效=true" : "").then(set行);
  useEffect(() => {
    刷新().catch((e) => set讯(String(e.message || e)));
  }, [含失效]);
  return (
    <div>
      <h1 className="题">差额清单</h1>
      <p className="述">
        快照余额与回放余额不一致时落在这里；冒烟通过时应为空或仅历史批。并户改挂后旧差额行置「已失效」留审计。
      </p>
      <div className="行">
        <label className="勾">
          <input type="checkbox" checked={含失效} onChange={(e) => set含失效(e.target.checked)} />
          含已失效行
        </label>
        <button className="次" onClick={() => 刷新().catch((e) => set讯(String(e.message || e)))}>刷新</button>
      </div>
      {讯 ? <p className="讯">{讯}</p> : null}
      {!行.length ? (
        <div className="空态">暂无差额行</div>
      ) : (
        <table>
          <thead>
            <tr>
              <th>回放批次</th>
              <th>账户键</th>
              <th>营业日</th>
              <th>快照余额</th>
              <th>回放余额</th>
              <th>差额</th>
              <th>原因</th>
              <th>状态</th>
            </tr>
          </thead>
          <tbody>
            {行.map((r) => (
              <tr key={r.编号}>
                <td>{r.回放批次编号}</td>
                <td>{r.账户键}</td>
                <td>{r.营业日}</td>
                <td>{r.快照余额 ?? "—"}</td>
                <td>{r.回放余额 ?? "—"}</td>
                <td>{r.差额}</td>
                <td>{r.原因}</td>
                <td>
                  <span className={r.状态 === "有效" ? "徽章 通" : "徽章 败"}>{r.状态 || "有效"}</span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
