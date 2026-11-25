import React, { useEffect, useState } from "react";
import { api } from "../api.js";

export default function 周期快照() {
  const [日, set日] = useState("");
  const [含归档, set含归档] = useState(false);
  const [行, set行] = useState([]);
  const [讯, set讯] = useState("");

  const 查询 = () => {
    const 参 = [];
    if (日) 参.push(`营业日=${encodeURIComponent(日)}`);
    if (含归档) 参.push("含归档=true");
    return 参.length ? `?${参.join("&")}` : "";
  };
  const 刷新 = () => api.快照(查询()).then(set行);

  useEffect(() => {
    刷新().catch((e) => set讯(String(e.message || e)));
  }, []);

  return (
    <div>
      <h1 className="题">周期快照</h1>
      <p className="述">
        每个账户每个营业日一行有效余额镜。并户后源户镜转「归档」只读：默认只列有效镜，按源键查有效镜为空。
      </p>
      <div className="行">
        <input value={日} onChange={(e) => set日(e.target.value)} placeholder="筛选营业日，可空" />
        <label className="勾">
          <input type="checkbox" checked={含归档} onChange={(e) => set含归档(e.target.checked)} />
          含归档只读行
        </label>
        <button className="次" onClick={() => 刷新().catch((e) => set讯(String(e.message || e)))}>刷新</button>
      </div>
      {讯 ? <p className="讯">{讯}</p> : null}
      {!行.length ? (
        <div className="空态">暂无快照</div>
      ) : (
        <table>
          <thead>
            <tr>
              <th>账户键</th>
              <th>营业日</th>
              <th>余额</th>
              <th>抽取批次</th>
              <th>来源</th>
              <th>状态</th>
            </tr>
          </thead>
          <tbody>
            {行.map((r) => (
              <tr key={r.快照键}>
                <td>{r.账户键}</td>
                <td>{r.营业日}</td>
                <td>{r.余额}</td>
                <td>{r.抽取批次编号}</td>
                <td>{r.来源}</td>
                <td>
                  <span className={r.状态 === "有效" ? "徽章 通" : "徽章 败"}>{r.状态}</span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
