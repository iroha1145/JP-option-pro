# 翻译完整性审查（2026-08-04）回应 — ja/en 篇

对象是 `JP-option-pro-翻译完整性审查报告-2026-08-04.md` 列出的 42 项。

**本轮范围由用户明确划定：只修 ja/en，中文界面下漏出日语的部分暂不动。**
所以报告的第一节（24 项 msgid 语种用错）与第五节（`新规进入` 假朋友）
整体不在本轮 —— 那两类的 en/ja 译文本来就是对的，问题只在 zh。

---

## 0. 一句话

报告第二、四节（**ja/en 会漏出原文** 的 17 项）全部核实属实并修完；
另外自查补了 4 项报告没抓到的同类问题；根因（后端生成的展示文没有任何
门禁）用 3 道机器闸门堵住。

---

## 1. 先核实，再动手

报告里的每一条都在代码里对过行号与实际行为，没有一条是照单全收。核实结论：

| 节 | 指控 | 核实 |
| --- | --- | --- |
| 二 | `News.tsx:27` `CATEGORY_FILTERS` 裸日文、直接 `{item}` 渲染 | 属实 |
| 二 | `StockDetail.tsx:890` `（週次）` 写死在 JSX | 属实 |
| 二 | `Market.tsx:254` eyebrow `SECTOR MATRIX · 33 業種` | 属实 |
| 二 | `screener/types.ts:105-109` `TURNOVER_OPTIONS` 5 项裸串 | 属实 |
| 四 | News 4 处分类渲染点未过 `t()` | 属实（且 **19 个分类值**，不止筛选条的 7 个） |
| 四 | `RowExpansion.tsx` `row.reasons` 未过 `t()` | 属实 |
| 四 | `Radar.tsx:232` `structure_label` 未过 `t()` | 属实 |
| 四 | `Research.tsx:195` `point_in_time_limits` 未过 `t()` | 属实 |
| 四 | `SideCards.tsx:49-53` `regime.label` / `spread_label` 未过 `t()` | 属实 |
| 四 | `strength_scan.py` 信用规制 5 值 + 警告，字典无词条 | 属实（6 条缺） |
| 四 | `vol_price_match.py` 3 条边界状态字典缺项 | 属实 |
| 四 | `earnings_service.py:148` `UPCOMING_COVERAGE_NOTE` 未过 `t()` | 属实 |

**报告没抓到、自查补上的 4 项**（同一类，都是后端下发值裸渲染）：

- `RowExpansion.tsx` 的 `priceAction.structure_label` —— 报告只点了
  `Radar.tsx` 的那一处，同一个字段在筛选器行展开里也是裸渲染。
- `RowExpansion.tsx` 的 `priceAction.pattern_labels` —— 同上，且用
  `join('、')` 写死了中日文的顿号（英文该是逗号+空格）。
- `News.tsx:305` 的 `importance_reasons` —— 后端 `classify.py` 组装的
  中文短句，同样裸渲染。
- `strength_scan.py` 的 `深度回撤`、regime 的第二条警告
  `200日線超の銘柄が3割未満（ブレッドス弱い）` 字典缺项。

**报告认定但本轮判定为不需要处理的 1 项**：`StrengthRow.tags`（`相对TOPIX强`
`接近52周高位` 等 6 个）。全仓库 grep 确认 **前端从不渲染这个字段**，
只有 `vol_price.tags` 会出现在画面上。给不显示的值加词条＝制造死代码，
而报告自己也把死词条 `'页'` 列为清理项。故不加。

---

## 2. 难点：数字混进句子，辞典就引不到了

三条后端文案是 f-string：

```python
warnings.append(f"ATR约{atr_pct:.1f}%，波动风险高")
```

出来的是 `ATR约7.3%，波动风险高` —— 每换一个数字就是一个新字符串，
辞典的任何键都不可能对上。这类**在 ja/en 下永远回退中文**，且加多少
词条都没用。

沿用第十三轮 `short_monitor/explain.py` 已经立好的办法：后端返回
**模板 + 参数**，置换交给前端 `t()`。这次把它抽成一个模块
`backend/app/services/display_text.py`，两处新用法共用：

```python
warnings.append(_line("ATR约{atr}%，波动风险高", atr=f"{atr_pct:.1f}"))
```

- `strength_scan`：`risk_penalty()` / `_annotate()` 返回 `_line()` 形，
  接口同时给出 `warnings`/`reasons`（中文置换好，旧消费者不坏）与
  `warning_items`/`reason_items`（模板形，UI 优先用）。
- `news/classify`：`事件类别: 決算/配当` 里被 `/` 拼起来的分类名同样引不到，
  用 `display_text.enumeration()` 拆成 `parts`，连**分隔符都交给语言**
  （中日顿号、英文逗号+空格）。存进 `importance_components` 时新旧并存，
  老新闻行没有 `reason_items` 就回退。

前端 `lib/explainText.ts` 相应放宽：`parts` 填哪个参数名、用什么分隔符，
由后端指定（默认仍是空卖监控用的 `moves` / `、`）。

## 3. 字典

新增 **66 条**（919 → 922 键，`dict_no_duplicates` 无重复）。

其中一部分 **msgid 是日文**（`順風` `決算` `週次` `≥ 1億円` …），因为后端常量
就是日文，而本轮不动中文侧。这是有意的取舍，字典里写了注释：
中文化时后端常量与字典键必须**同时**改。

新闻分类的键是 **API 的筛选值本身**，`CATEGORY_FILTERS` 只在显示时套 `t()`
—— 把译好的字符串送回后端会一条都筛不出来，代码里也加了注释。

## 4. 三道闸门（真正的交付物）

这批问题的根因不是某几行漏写，是**后端生成的展示文一个检查都没有**。
补三道：

| 闸门 | 看什么 | 覆盖 |
| --- | --- | --- |
| `tests/test_backend_text_is_translatable.py` | 后端能吐出的展示文 ⊆ 字典键，且 en/ja **两栏都非空** | 97 条 |
| `frontend-src/tests/explain_text.mjs` | 字典里**有**的东西，UI 是否真的引到了（3 语言各跑一遍进程） | 模板/参数/嵌套列举/回退 |
| `frontend-src/tests/dict_no_duplicates.mjs` | 重复键（既有）+ **扫描是否有漏数**（新增） | 922/922 |

第一道的字符串来源有三路，都**不在测试里抄写字面量**：

1. AST 扫 `display_text.line()` / `enumeration()` 的第一个实参 ——
   只要守住「展示文走这个函数」的约定，以后新写的句子自动进网；
2. `import` 后端的标签常量（`_STRUCTURE_LABELS`、`CATEGORY_WEIGHTS`、
   `POINT_IN_TIME_LIMITS`、`UPCOMING_COVERAGE_NOTE` …）；
3. 只在分支里出现的，**实际调用函数**收集（`describe()` / `classify()`）。

为此把 `strength_scan` 里内联的 regime 标签提成常量 `REGIME_LABELS` /
`REGIME_SPREAD_LABEL` —— 画面上的字符串不该埋在函数体里。

闸门本身也验过会失败：删一条词条、把 en 置空、把 ja 置空、折行写法的重复键，
四种情况都各自报出来了。

### 顺手修掉的两个「门禁自己坏了」

- `test_backend_text_is_translatable` 原来的字典解析正则用 `^\s*`，
  而 `\s` 和 `[^:]` **都能匹配换行** —— 一条注释行会把紧跟其后的键行整个吞掉，
  那个键就从集合里消失，变成「字典里没有」的误报。已改成逐行解析，
  并与 node 实际加载的 `DICT` 对拍：922 键、922 组值，全一致。
- `dict_no_duplicates.mjs` 要求 `[` 与键同行，漏掉了 3 条折行写法的条目
  （919 vs 922）。漏看的键即使重复也会被放行。已修，并加了「扫描数必须等于
  实际键数」的自检 —— 以后再漏数会直接报错而不是静静少算。

## 5. 浏览器实测

本机没有后端（生产从这里也连不通），用临时 fixture 拦 `fetch`，只验渲染路径。
`en` / `ja` 各走一遍，**筛选器、新闻、决算、Research** 四页：

- 新闻：筛选条 `Earnings / Guidance revision / M&A / Tender offer / …`、
  热点与条目分类、经济日历 `Monetary policy` `Prices`
- 重要度依据：`Event type: Earnings/Dividend · Linked to listed companies ·
  Published recently` —— 嵌套列举、分隔符、参数翻译全通
- 筛选器行展开（en）：`ATR around 7.3% — high volatility risk`、
  `Margin trading restricted (extra collateral / new positions halted)`、
  `HH+HL uptrend`、`Bullish engulfing, Hammer`、
  `Turnover about 1.8× the 20-day average`
- 同一页（ja）：`ATR は約7.3%。変動リスクが高いです`、
  `信用取引が規制中（増担保・申込停止）`、`陽の包み足、ハンマー`、
  `売買代金が20日平均の約1.8倍`、`順風`、
  `グロース対プライム 20日中央値差` —— 后端来源的文本里没有一处中文残留
- 决算「覆盖口径」与 Research「点时限制」三句：整段英文

（过程中 fixture 把 `翌営業日` 手抄成 `翻営業日`，页面立刻不翻译了 ——
反过来说明查表是**逐字精确**的。改成直接从后端常量注入后正常。）

## 6. 明确没做的

- **报告第一节的 24 项 msgid 语种用错**（`目安` `確定` `株` `実績` `対予想`
  `進捗` `後場寄り` `寄付` `日経225` 等）。按本轮范围据置。这些的 en/ja
  译文本来就正确，问题只在「zh 直接返回 msgid」。真要修，
  `earnings/types.ts` 的 `statusMeta()` 是单点收益最大的一处。
- **第五节 `新规进入`**（借用日语「新規」的假朋友）。同上，zh 侧问题。
- 字典死代码 `'页'`（`['', '']`，全仓库无调用点）。清理项，与 ja/en 无关。
- 后端日文常量改写为中文。本轮把它们当 msgid 用了 —— 中文化时要与字典键
  一起动，已在字典注释里写明。

## 7. 门禁现状

`pytest 425 通过` · `tsc -p tsconfig.app.json --noEmit 干净` ·
`dict 922 键无重复且无漏数` · `explain_text 3 语言通过` ·
`提交产物 diff -r 一致`
