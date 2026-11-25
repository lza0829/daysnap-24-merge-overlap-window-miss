import React, { useEffect, useState } from "react";
import { api } from "../api.js";

export default function 账户册() {
  const [行, set行] = useState([]);
  const [讯, set讯] = useState("");
  useEffect(() => {
    api.账户().then(set行).catch((e) => set讯(String(e.message || e)));
  }, []);
  return (
    <div>
      <h1 className="题">账户册</h1>
      <p className="述">
        种子账户。金额单位为分。并户后源户状态为「已并户」、去向指向目标户；历史镜转只读归档，
        重叠日持窗票强制坍缩——源键正式镜清空、隔离归档可读，目标键独存正式镜。
      </p>
      {讯 ? <p className="讯">{讯}</p> : null}
      {!行.length ? (
        <div className="空态">暂无账户</div>
      ) : (
        <table>
          <thead>
            <tr>
              <th>账户键</th>
              <th>户名</th>
              <th>币种</th>
              <th>开户营业日</th>
              <th>状态</th>
              <th>并户去向</th>
              <th>并户凭证</th>
            </tr>
          </thead>
          <tbody>
            {行.map((r) => (
              <tr key={r.账户键}>
                <td>{r.账户键}</td>
                <td>{r.户名}</td>
                <td>{r.币种}</td>
                <td>{r.开户营业日}</td>
                <td>
                  <span className={r.状态 === "正常" ? "徽章 通" : "徽章 败"}>{r.状态}</span>
                </td>
                <td>{r.并户去向 || "—"}</td>
                <td>{r.并户凭证 || "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
