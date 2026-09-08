# PR #17 收尾验证

本轮从 `fe3403875f78a41e60d74a124a627f533a73781a` 继续修复，没有重做此前界面升级。

修复内容：

- 证券代码按后端规则匹配完整身份，保留字母及有意义的第五位。`285A` 与 `285A0` 相同，`285A` 与 `285B` 不同，`7203` 与 `72031` 也不同。
- 股票、指数同步的检查点已到目标日时，允许重取该日，取得迟到数据和同日更正；更早目标不倒退检查点，历史增量范围不变。
- 普通筛选表恢复同时核对交易日和发布编号。强度发布已成功、普通表写入或完成记录失败时，下一轮仍会补齐；恢复完成后不重复写表。
- 选股页等身份确认后才启动首次读取；身份切换会重新读取并清理旧任务状态。显式查询及已核验的后台更新完成后，旧静默请求不能覆盖结果；后台更新失败也不会丢弃尚未完成的首次查询。

本地验证：

| 验证 | 结果 |
|---|---|
| 后端完整测试 | 578 项通过；新增同日补拉 12 项、同日恢复 5 项 |
| 前端定向检查 | 28 项通过；其中证券身份新增 4 组 |
| 生产构建与提交产物比较 | 通过，`frontend-src/dist` 与 `frontend` 完全一致 |
| 字典与三语言文案 | 1,271 个键无重复，中、英、日文案检查通过 |
| 真实浏览器受控交互 | 14 项通过，含身份慢返回、旧请求晚返回、任务失败及超时 |
| 页面到独立工作进程 | 点击真实按钮、真实队列、独立进程执行、精确发布编号读回通过 |
| 受影响页面显示 | 1440、390 像素下检查选股页与 `285A` 个股页，图表成功显示且无横向溢出 |

浏览器验证执行了实际页面组件。14 项受控场景只替换接口的返回内容或返回顺序，基于真实接口结构；另一次完整流程不拦截页面请求，启动了真实接口服务与独立的 `WorkerSupervisor` 进程。数据供应商使用测试替身，数据库为隔离合成数据，未连接生产数据供应商。

完整流程在同一交易日更正一条成交额输入后，由页面提交更新任务。结果为 `published`；任务承诺的发布编号与页面读回编号相同，且区别于更新前编号。`strength_snapshot` 与 `screener_snapshot` 的完成记录也指向同一个新发布。

可重放的浏览器脚本：

- `frontend-src/tests/screener-browser.mjs`：14 个交互回归。当前浏览器页需属于已填充合成数据的本地站点。
- `frontend-src/tests/screener-worker-browser.mjs`：真实队列及独立工作进程验证。先启动 `tests/support/synthetic_worker.py`，再通过 `CoreRepository` 更正一条合法日线输入，不预先重建发布。

从仓库根目录执行，输出目录预先创建为 `output/pr17-finalize`：

```sh
playwright-cli open http://127.0.0.1:2117/screener --headed
playwright-cli run-code --filename frontend-src/tests/screener-browser.mjs
playwright-cli eval 'window.__screenerBrowserResults'
```

第二个脚本在相同的独立测试环境执行：

```sh
playwright-cli run-code --filename frontend-src/tests/screener-worker-browser.mjs
playwright-cli eval 'window.__realWorkerResult'
```

脚本失败会返回错误；每项结果和页面截图、浏览器轨迹写入测试输出目录。轨迹分别为 `screener-browser-trace.zip` 与 `real-worker-trace.zip`。它们是本地验收材料，不应把它们描述为持续集成（CI）中的浏览器测试。远程 CI 仍执行仓库原有后端、前端检查及产物校验。

本轮没有改变指数数据不足时允许降级发布的既有策略，没有执行合并或生产部署。
