import React, { useEffect, useState } from "react";
import { api } from "../api.js";

const 空表单 = { 源: "户甲", 目标: "户乙", 生效日: "2026-11-22" };

export default function 并户继承() {
  const [凭, set凭] = useState([]);
  const [选, set选] = useState("");
  const [视, set视] = useState(null);
  const [表单, set表单] = useState(空表单);
  const [讯, set讯] = useState("");

  const 刷新列表 = async () => {
    const 行 = await api.并户();
    set凭(行);
    if (!选 && 行.length) set选(行[0].凭证编号);
  };

  const 取视 = (凭证) => {
    if (!凭证) return Promise.resolve();
    return api.并户继承(凭证).then(set视);
  };

  useEffect(() => {
    刷新列表().catch((e) => set讯(String(e.message || e)));
  }, []);

  useEffect(() => {
    if (选) 取视(选).catch((e) => set讯(String(e.message || e)));
  }, [选]);

  const 跑夹具 = (名) =>
    api
      .并户夹具(名)
      .then(async (r) => {
        const 校验 = (r.校验 || []).map((x) => `${x.项}=${JSON.stringify(x.值)}`).join("；");
        set讯(`夹具 ${名} 完成；凭证 ${r.凭证编号}；${校验}`);
        const 行 = await api.并户();
        set凭(行);
        if (r.凭证编号) {
          set选(r.凭证编号);
          await 取视(r.凭证编号);
        }
      })
      .catch((e) => set讯(String(e.message || e)));

  const 提交并户 = () =>
    api
      .执行并户(表单)
      .then(async (r) => {
        set讯(`并户完成：${r.源} → ${r.目标}，生效 ${r.生效日}，结转 ${r.源结转余额}`);
        const 行 = await api.并户();
        set凭(行);
        set选(r.凭证编号);
        await 取视(r.凭证编号);
      })
      .catch((e) => set讯(String(e.message || e)));

  return (
    <div>
      <h1 className="题">并户继承镜</h1>
      <p className="述">
        并户不是只改账户状态字：源户历史镜转「归档」只读，目标户接续源户已公布镜链条，流水改挂目标；
        并户凭证、快照、流水、差额同事务同成败。口径为源键只读归档。
      </p>

      <div className="提示条">
        两户均有镜后才能并户。目标生效日余额 = 目标前日 + 源户结转 + 当日净额，且只加一次；按源键默认列有效镜为空。
      </div>

      <div className="行">
        <button onClick={() => 跑夹具("并户继承样例.json")}>跑并户继承夹具</button>
        <button className="水" onClick={() => 跑夹具("并户并发样例.json")}>
          跑并户并发夹具
        </button>
        <button className="次" onClick={() => 刷新列表().catch((e) => set讯(String(e.message || e)))}>
          刷新凭证
        </button>
      </div>
      {讯 ? <p className="讯">{讯}</p> : null}

      <div className="段">
        <h2 className="段题">手工并户</h2>
        <div className="行">
          <input value={表单.源} onChange={(e) => set表单({ ...表单, 源: e.target.value })} placeholder="源账户键" />
          <input
            value={表单.目标}
            onChange={(e) => set表单({ ...表单, 目标: e.target.value })}
            placeholder="目标账户键"
          />
          <input
            value={表单.生效日}
            onChange={(e) => set表单({ ...表单, 生效日: e.target.value })}
            placeholder="生效日 YYYY-MM-DD"
          />
          <button onClick={提交并户}>执行并户</button>
        </div>
      </div>

      <div className="段">
        <h2 className="段题">并户凭证</h2>
        {!凭.length ? (
          <div className="空态">尚无并户凭证</div>
        ) : (
          <>
            <div className="行">
              <select value={选} onChange={(e) => set选(e.target.value)}>
                {凭.map((x) => (
                  <option key={x.凭证编号} value={x.凭证编号}>
                    {x.凭证编号}
                  </option>
                ))}
              </select>
            </div>
            <table>
              <thead>
                <tr>
                  <th>凭证编号</th>
                  <th>源</th>
                  <th>目标</th>
                  <th>生效日</th>
                  <th>源末镜日</th>
                  <th>源结转余额</th>
                  <th>源键暴露</th>
                  <th>valid</th>
                </tr>
              </thead>
              <tbody>
                {凭.map((x) => (
                  <tr key={x.凭证编号}>
                    <td>{x.凭证编号}</td>
                    <td>{x.源账户键}</td>
                    <td>{x.目标账户键}</td>
                    <td>{x.生效日}</td>
                    <td>{x.源末镜日}</td>
                    <td>{x.源结转余额}</td>
                    <td>
                      <span className={x.源键暴露 ? "徽章 通" : "徽章 败"}>
                        {x.源键暴露 ? "暴露·只读归档" : "不暴露"}
                      </span>
                    </td>
                    <td>
                      <span className={x.valid ? "徽章 通" : "徽章 败"}>{x.valid ? "true" : "false"}</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        )}
      </div>

      {视 ? (
        <div className="段">
          <h2 className="段题">
            继承只读视图 · {视.凭证编号}（{视.口径}）
          </h2>
          <div className="两栏">
            <div>
              <h3 className="段题">目标继承链 · {视.目标}</h3>
              {!视.目标继承链.length ? (
                <div className="空态">无有效镜</div>
              ) : (
                <ul className="链">
                  {视.目标继承链.map((x) => (
                    <li key={x.营业日}>
                      <span>{x.营业日}</span>
                      <b>{x.余额}</b>
                      <span className="徽章 通">{x.状态}</span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
            <div>
              <h3 className="段题">源归档链 · {视.源}</h3>
              {!视.源归档链.length ? (
                <div className="空态">无归档行</div>
              ) : (
                <ul className="链">
                  {视.源归档链.map((x) => (
                    <li className="归档" key={x.营业日}>
                      <span>{x.营业日}</span>
                      <b>{x.余额}</b>
                      <span className="徽章 败">{x.状态}</span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
