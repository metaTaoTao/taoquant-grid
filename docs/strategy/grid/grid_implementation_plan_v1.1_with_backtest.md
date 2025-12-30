# 链动中性网格策略系统实现规格（Engineering Spec v1）

> 用途：把《中性网格策略——治理/逻辑/风控（Part A/B/C）》落地为**程序员可直接开发**的完整系统规格。  
> 范围：不仅包含 Adaptive Core Zone，还包含状态机、风控、执行、配置、日志审计、持久化、测试用例与目录结构。  
> 目标：你把这份文档交给程序员，他可以直接拆任务、建仓库、写代码、做回放测试并上线灰度。

---

## 目录

- [0. 目标与非目标](#0-目标与非目标)
- [1. 系统总览（模块分解）](#1-系统总览模块分解)
- [2. 数据与对象模型（统一口径）](#2-数据与对象模型统一口径)
- [3. 关键规则的工程化定义（避免歧义）](#3-关键规则的工程化定义避免歧义)
- [4. 状态机（严格实现）](#4-状态机严格实现)
- [5. 优势识别系统（机会窗口 + Core Zone）](#5-优势识别系统机会窗口--core-zone)
- [6. 网格生成与订单窗口（GridEngine）](#6-网格生成与订单窗口gridengine)
- [7. 进攻性实现（Skew + 火力集中 + 风险预算回收）](#7-进攻性实现skew--火力集中--风险预算回收)
- [8. 破位分类与 Re-anchor（结构迁移）](#8-破位分类与-re-anchor结构迁移)
- [9. 止损体系（RiskEngine）](#9-止损体系riskengine)
- [10. 审计、日志与目录结构（可复盘可审计）](#10-审计日志与目录结构可复盘可审计)
- [11. 配置文件（grid_strategy.yaml）最小字段集合](#11-配置文件grid_strategyyaml最小字段集合)
- [12. 运行时流程（主循环与控制循环）](#12-运行时流程主循环与控制循环)
- [13. 回测 / 回放（Backtest & Replay）实现规格](#13-回测--回放backtest--replay实现规格)
- [14. 测试用例（必须具备）](#14-测试用例必须具备)
- [15. 交付包建议（最小可交付）](#15-交付包建议最小可交付)

---

## 0. 目标与非目标

### 0.1 目标（必须满足）

1) **输入边界（交易员职责）**
- 交易员仅提供：
  - Outer Range：`[Range_Low, Range_High]`（宏观区间）
  - 趋势/市场环境判断 Gate（是否允许震荡型策略运行）
  - 对轻微单边的容忍程度（允许偏移与上限）

2) **系统必须自动完成**
- **优势识别与火力集中**（策略逻辑层落地）
  - Adaptive Opportunity Window：机会是否仍成立
  - Adaptive Core Zone：优势集中区域
- **内生风险递减与风险预算回收**
  - 在优势兑现后自动收火、降速、进入 Harvest-to-Exit
  - 将“零成本持仓/风险预算回收”做成可执行触发器
- **四态风控状态机执行**
  - NORMAL / DEFENSIVE / DAMAGE_CONTROL / EMERGENCY_STOP
  - 不允许“半状态”、不允许绕过强制规则
- **结构性事件必须可审计**
  - Re-anchor / Emergency Stop / 强制退出
  - 必须有事件日志与快照

### 0.2 非目标（v1 不做）

- 不量化交易员趋势判断（由交易员输入 gate）
- 不做跨交易所智能路由 / 最优成交拆单（可后续扩展）
- 不做全自动“区间选取”（Outer Range 由交易员输入）
- 不做多策略组合调度（先把中性网格跑稳）

---

## 1. 系统总览（模块分解）

### 1.1 核心模块（建议按此分包/分目录）

1) **MarketData**
- 行情：价格、K线（bar）
- 交易回报：成交、撤单、挂单状态
- 账户：权益、保证金、可用余额、强平距离（若可得）

2) **OpportunityGate（交易员 Gate）**
- 读取交易员输入：
  - outer_range_low/high
  - trend_gate（允许/禁止）
  - allow_mild_bias（允许轻微单边）
- 负责“是否允许启动/继续运行”的宏观门槛

3) **StateMachine（四态）**
- 维护策略运行状态：NORMAL/DEFENSIVE/DAMAGE_CONTROL/EMERGENCY_STOP
- 根据风险触发器与结构判定迁移状态
- 输出：当前状态 + 允许行为集

4) **AdvantageEngine（优势识别）**
- 计算 Adaptive Opportunity Window（机会是否仍成立）
- 计算 Adaptive Core Zone（优势集中区域）
- 输出：core_zone_low/high、机会衰减/有效信号、相关指标

5) **GridEngine（网格逻辑）**
- 生成网格层级、活跃窗口、撤换外层订单
- 在不同 state 下，执行不同权限（冻结新增 buy / reduce-only 等）
- 输出：目标订单集（desired orders）

6) **SkewEngine（偏置定价）**
- 在合法条件下启用（只在 NORMAL + core_zone + 低库存）
- 通过调整 step/offset/refresh 方向性偏置，提高 cycle 完成率
- 必须避免“越跌越买”的坏路径

7) **RiskEngine（硬风控）**
- Inventory / Margin / MaxDD / Structural Break / Liquidity Gap
- 硬规则触发后强制切换状态或强制减仓/退出

8) **DeRiskEngine（风险递减）**
- 边际效率下降、breakeven 改善变平、机会衰减、house-money 状态触发
- 输出：降速指令（关闭 skew、收缩窗口、提高 step、Harvest-to-Exit）

9) **Execution（执行）**
- 下单/撤单/改单
- Reduce-only 支持
- 订单幂等、重试、限频、异常处理

10) **Audit & Journal（审计与日志）**
- 结构性事件（Re-anchor / Emergency Stop / Forced Exit）
- 状态迁移（STATE_CHANGE）
- 参数更新（PARAM_UPDATE）
- 全部带 snapshot，便于复盘与回放

---

### 1.2 进程模型（推荐“两循环”）

- `trade_loop`（常驻，事件驱动）
  - 处理成交、风险检查、状态机更新、下单/撤单
- `control_loop`（常驻或定时）
  - 4H/1D 更新：vol、spacing、core_zone、机会窗口评估、derisk 评估

---

## 2. 数据与对象模型（统一口径）

### 2.1 时间与粒度

- 执行：事件驱动（tick/成交回报）
- 统计：基于 `bar_tf`（建议 1m 或 5m）
- 高层更新：4H（默认）/ 1D（可选）

### 2.2 必须持久化的状态量（能断电恢复）

- `outer_range_low`, `outer_range_high`（交易员输入）
- `core_zone_low`, `core_zone_high`（系统计算）
- `state`：当前四态
- `inventory_qty`, `inventory_ratio`
- `breakeven_price`（含手续费/滑点）
- `realized_pnl`, `unrealized_pnl`, `equity`
- `margin_usage`, `liq_distance`（若可得）
- `active_orders`（订单列表：side/price/qty/reduce_only/tag）
- `risk_budget_remaining`（可用风险额度指标，允许简化）

### 2.3 关键衍生指标（每 bar 或每事件更新）

- `inventory_slope`：inventory_ratio 的变化速度
- `vol`：实现波动率（按你们口径）
- `vol_spike`：波动冲击信号（按你们口径）
- `structural_break_confirmed`：结构性破位确认信号
- `cycle_activity`：震荡闭环/穿越活跃度
- `inv_reversion_speed`：库存回中速度
- `breakeven_slope`：成本改善速度

---

## 3. 关键规则的工程化定义（避免歧义）

### 3.1 Outer Range（交易员输入）

- `outer_range = [L, H]`：策略允许活动的大边界
- 价格越界不等于立刻停机；由 StateMachine + Break Protocol 决定

### 3.2 Inventory（第一风险变量）

- `MAX_INVENTORY`：硬上限（需明确口径：币数量 / USD 名义 / 杠杆后名义）
- `inventory_ratio = abs(inventory_qty) / MAX_INVENTORY`
- 必须计算 `inventory_slope` 作为“加速堆仓”风险输入

### 3.3 Breakeven（零成本持仓的核心变量）

- `breakeven_price`：加权平均成本 + 预估手续费/滑点（必须统一口径）
- “零成本持仓/house-money”在工程上不要求成本=0，而是：
  - **锁定优势 ≥ 未来剩余路径风险**（见 7.3）

---

## 4. 状态机（严格实现）

### 4.1 状态与允许行为矩阵（强约束）

| State | 允许新增 buy | 允许补 buy | 允许 sell | 允许 reduce-only | 允许 re-anchor |
|---|---:|---:|---:|---:|---:|
| NORMAL | 是 | 是 | 是 | 否（可选） | 是（受约束） |
| DEFENSIVE | 否（冻结新增 buy） | 否 | 是（用于减仓） | 是（推荐） | 否（默认不） |
| DAMAGE_CONTROL | 否 | 否 | 是（分段减仓） | 是（强制） | 否 |
| EMERGENCY_STOP | 否 | 否 | 是（紧急处理） | 是（强制） | 否 |

> 说明：DEFENSIVE 的关键是“冻结新增 buy、禁止扩大 inventory、允许 sell 减仓、撤销外层高风险 buy”。

---

### 4.2 状态迁移触发（最小可行规则集）

#### NORMAL → DEFENSIVE（任一满足）
- 价格触边：`price <= L` 或 `price >= H`
- `inventory_ratio >= inv_warn`（建议默认 0.55）
- `vol_spike == true`

#### DEFENSIVE → DAMAGE_CONTROL（任一满足）
- `inventory_ratio >= inv_damage`（建议默认 0.70）
- `structural_break_confirmed == true`
- `risk_budget_stop == true`（见 9.2）

#### 任意 → EMERGENCY_STOP（任一满足）
- `liquidity_gap == true`
- `liq_distance < threshold`（若可得）
- 交易所/接口异常严重（无法撤单/无法下单/价格断流）

#### DEFENSIVE/DAMAGE_CONTROL → NORMAL（必须全部满足）
- `price` 回到 `[L, H]`
- `inventory_ratio <= inv_back_to_normal`（建议 0.35~0.45）
- `structural_break_confirmed == false`
- （可选）机会窗口有效（OpportunityWindow not Decay）

---

## 5. 优势识别系统（机会窗口 + Core Zone）

> 目标：把“看对时赚够”的进攻来源绑定为“优势集中区域”，而不是提高风险上限。

### 5.1 Adaptive Opportunity Window（机会是否仍成立）

每 `bar_tf` 更新指标，每 4H 聚合决策一次（建议）。

定义三个信号：

1) **Cycle Activity（震荡循环活跃度）**
- 统计过去 `T_window`（建议 24h 或 48h）内：
  - 完成的 buy→sell 或 sell→buy 闭环次数 `cycle_count`
  - 或价格穿越网格层次数 `cross_count`
- `cycle_activity = cycle_count / time`

2) **Inventory Reversion（库存回中能力）**
- inventory 偏离目标带（例如 |inv| > 0.2）后，回到目标带的平均时间
- `inv_reversion_speed = 1 / avg_time_to_revert`

3) **Breakeven Improvement（成本下移速度）**
- `breakeven_slope = -(breakeven_price[t] - breakeven_price[t-Δ]) / Δ`
- slope ≤ 0 表示没有改善或恶化

**机会窗口成立条件（建议）**
- `cycle_activity >= min_cycle_activity`
- `inv_reversion_speed >= min_inv_reversion_speed`
- `breakeven_slope >= min_breakeven_slope`（至少不显著恶化）

若任一条件连续 `N_fail` 次失败（建议 3 次 4H 检查），机会窗口进入 **Decay**，触发 DeRiskEngine（见 7.3）。

---

### 5.2 Adaptive Core Zone（优势集中区域）

在 `outer_range` 内对价格分箱（price bins），统计 `T_zone`（建议 48h）：

- `fill_density[bin]`：该 bin 成交/闭环次数（或成交量/成交笔数）
- `inv_revert_score[bin]`：进入该 bin 后库存回中更快的得分
- `breakeven_gain[bin]`：该 bin 附近 breakeven 改善更明显的得分

综合优势得分：
- `adv_score[bin] = w1*norm(fill_density) + w2*norm(inv_revert_score) + w3*norm(breakeven_gain)`

Core Zone 选取规则（确定、可实现）：
- 从最高 `adv_score` 的连续 bins 中取最短连续区间
- 使其累计覆盖 `>= zone_cover`（建议 0.65） 的总 `fill_density`
- 输出：`core_zone_low/high`

更新频率与防抖：
- **最多每 4H 更新一次**
- 若新旧 core_zone 变化 < `zone_change_threshold`（建议按区间宽度 10%），则保持不变，避免追价。

---

## 6. 网格生成与订单窗口（GridEngine）

### 6.1 Active Grid Window（活跃订单窗口）

配置：
- `N_buy_active`：最多活跃 buy 层数
- `M_sell_active`：最多活跃 sell 层数

规则：
- 内层订单优先保留
- 外层订单允许被替换/撤销
- spacing 改变 ≠ 增加订单数量  
  spacing 改变 = 重分配风险预算

不同 state 的窗口策略：
- NORMAL：窗口覆盖 core_zone 为主，buffer 区稀疏
- DEFENSIVE：窗口收缩；**不新增 buy**
- DAMAGE_CONTROL：reduce-only；以分段减仓为主

---

### 6.2 Grid Spacing（动态间距）

- `base_step`：基础层间距（来源：ATR 或 realized vol）
- `step_core = base_step * core_compress_factor`（例如 0.7）
- `step_buffer = base_step * buffer_expand_factor`（例如 1.3）

更新频率：
- vol 计算：每根 K 线（bar）
- spacing 更新：4H 或 1D（默认 4H）

---

### 6.3 Edge Decay（边缘递减机制）

当价格接近 outer_range 边缘（例如距 L 或 H 小于 `edge_band`）：
- 单层下单 size 递减：`order_size *= edge_decay_factor^k`
- 进入边缘缓冲区后：
  - 禁止新增仓位
  - 只允许减仓（sell 或 reduce-only）

---

## 7. 进攻性实现（Skew + 火力集中 + 风险预算回收）

> 原则：进攻只来自“提高优势区 turnover”，不来自“提高风险上限”；并且尽量不触发盾（Part C）。

### 7.1 SkewEngine（偏置定价）三重门控（必须）

Skew 仅在同时满足时启用：
- `state == NORMAL`
- `price ∈ core_zone`
- `inventory_ratio <= inv_skew_max`（建议 0.40）

Skew 输入：
- `pos_in_core = (price - core_mid) / core_half_width`（[-1, 1]）
- `inv_headroom = 1 - inventory_ratio / inv_skew_max`（[0, 1]）

Skew 输出（避免越跌越买）：
- 目标：**提高 cycle 完成率**、加速回中与 breakeven 改善
- 推荐“对称压缩、受库存门控”的实现（示例）：
  - `step_buy  = step_core * (1 - skew_max * clamp(-pos_in_core,0,1) * inv_headroom)`
  - `step_sell = step_core * (1 - skew_max * clamp(+pos_in_core,0,1) * inv_headroom)`
- `skew_max` 建议上限 0.25（最多压缩 25%）

> 说明：这类 skew 的本质是“在优势区提高成交效率”，不是加杠杆；库存一旦偏大，skew 自动归零。

---

### 7.2 火力集中（只提高 turnover，不提高上限）

仅在 NORMAL + core_zone 时允许增强项：
- 更快 refresh（成交后补单延迟更短）
- 更密 step（受 skew 上限与 inv 门控）
- 更紧的 active window 贴合 core_zone（提升双边成交频率）

严禁：
- 提高 `MAX_INVENTORY`
- 在 DEFENSIVE/DAMAGE_CONTROL 继续加速堆仓

---

### 7.3 零成本持仓 / 风险预算回收（DeRiskEngine）

把“优势兑现后回收风险预算”工程化为可触发规则。

定义：
- `remaining_path_risk`：在可接受最坏路径下的预估损失  
  - 示例：`remaining_path_risk = (breakeven_price - worst_price) * position_qty + fees_slippage_buffer`
- `locked_in_advantage`：已锁定优势（可简化）
  - 示例：`locked_in_advantage = realized_pnl - fees_paid`

触发 DeRisk 的条件（满足任一）：
1) **边际效率下降**
- `cycle_efficiency = pnl_per_inventory_turnover` 显著下降超过阈值
2) **breakeven 改善变平**
- `breakeven_slope` 接近 0 或转负
3) **house-money 状态**
- `locked_in_advantage >= remaining_path_risk`
4) **机会窗口进入 Decay**
- 5.1 中连续失败达到阈值
5) **机会超时**
- `opportunity_timeout`（例如 72h）

DeRisk 动作（按顺序执行）：
1) 关闭 skew
2) 收缩 active window（减少 N/M）
3) 提高 buffer step（降低成交频率）
4) 进入 `Harvest-to-Exit`：
   - 仅做有利于 inventory 回中、降低路径风险的交易
   - 必要时 reduce-only

---

## 8. 破位分类与 Re-anchor（结构迁移）

### 8.1 假破位（False Break）

判定（最小规则建议）：
- 价格短暂越界，但收盘未连续 `K` 根在区间外（K=2~3）
- 且 `vol_spike` 不持续（或很快回落）

动作：
- 维持 DEFENSIVE
- 不 re-anchor
- 反弹优先减仓

---

### 8.2 结构性破位（Structural Break Confirmed）

判定（最小规则建议）：
- 连续 `K` 根收盘在区间外（K=3）
- 或交易员 gate 明确标记“趋势显著/不允许震荡策略”

合法动作（三选一）：
1) 部分减仓后 re-anchor
2) 组合级止损退出
3) 冻结 + 被动退出（反弹失败则转止损）

---

### 8.3 流动性事件/黑天鹅

- 直接 EMERGENCY_STOP
- 生存优先：立即停止网格逻辑，快速降杠杆/平仓（reduce-only）

---

### 8.4 Re-anchor 硬规则（必须强制）

- `inventory_ratio > 0.60` → **禁止 re-anchor**
- 必须先减仓至 `0.40~0.50` 才允许
- 新结构必须：
  - 区间更小
  - spacing 更稀疏
  - 仓位上限更低
  - 初期 reduce-only（或显著降速）

工程建议：
- `reanchor_request` 必须写入审计事件（见 10），并记录原因与快照

---

## 9. 止损体系（RiskEngine）

### 9.1 Inventory Stop（仓位止损）

- 触发：`inventory_ratio >= inv_stop`（默认建议 0.85）
- 动作：
  - 切换到 DAMAGE_CONTROL
  - 撤销所有新增风险订单
  - 分段减仓至 `inventory_ratio <= 0.40~0.50`

---

### 9.2 Risk Budget Stop（保证金/回撤）

- 触发：
  - 组合回撤 ≥ `max_dd`
  - 或 `margin_usage >= margin_cap`
- 动作：
  - 强制减仓
  - 无法恢复则直接退出（forced exit）

---

### 9.3 Structural Stop（结构止损）

- 触发：`structural_break_confirmed == true`
- 动作：
  - 若满足 re-anchor 前置条件（先降仓）→ re-anchor
  - 否则直接退出/进入 DAMAGE_CONTROL

---

### 9.4 Emergency Stop（紧急止损）

- 触发：流动性/系统性风险（gap、无法撤单、价格断流等）
- 动作：立即平仓/降杠杆，暂停策略，要求人工复核

---

## 10. 审计、日志与目录结构（可复盘可审计）

### 10.1 必须记录的事件（Audit Events）

事件类型：
- `REANCHOR`
- `EMERGENCY_STOP`
- `FORCED_EXIT`
- `STATE_CHANGE`
- `PARAM_UPDATE`

事件字段（建议 schema）：
- `event_id`, `timestamp`
- `event_type`
- `reason`（触发规则名/枚举）
- `snapshot`：
  - `price`, `state`, `inventory_ratio`, `breakeven_price`
  - `realized/unrealized_pnl`, `equity`, `margin_usage`
  - `outer_range`, `core_zone`
  - `active_orders_summary`（数量、最大偏离、reduce-only 比例）

写入形式：
- `audit_events.jsonl`（append-only，便于回放与审计）

---

### 10.2 推荐目录结构（程序员按此建仓库）

> 说明：以下为 **Markdown 代码块**格式，可直接复制粘贴到你的文档中。

### 10.2 推荐目录结构（程序员按此建仓库）

> 说明：以下为项目目录结构示意。

```text
project/
  config/
    grid_strategy.yaml
  docs/
    engineering/
      GridSystem_Spec_v1.md
    strategy/
      Liandong_Neutral_Grid_Policy.md
  src/
    market_data/
      __init__.py
      feeds.py
      bars.py
      account.py
    opportunity_gate/
      __init__.py
      gate.py
    state_machine/
      __init__.py
      states.py
      transitions.py
    advantage_engine/
      __init__.py
      opportunity_window.py
      core_zone.py
      metrics.py
    grid_engine/
      __init__.py
      grid_builder.py
      active_window.py
      spacing.py
    skew_engine/
      __init__.py
      skew.py
    risk_engine/
      __init__.py
      triggers.py
      stops.py
      break_protocol.py
    derisk_engine/
      __init__.py
      derisk.py
      harvest_mode.py
    execution/
      __init__.py
      broker.py
      order_manager.py
      rate_limit.py
      retry.py
    audit/
      __init__.py
      events.py
      journal.py
      snapshot.py
    utils/
      __init__.py
      types.py
      timeutils.py
  run/
    run_trade_loop.py
    run_control_loop.py
    run_backtest_replay.py
  data/
    state_store.json
    metrics_store.parquet
    fills.parquet
  logs/
    trade.log
    control.log
    audit_events.jsonl
  tests/
    test_state_machine.py
    test_risk_triggers.py
    test_core_zone.py
    test_derisk.py
    test_reanchor_rules.py
```

---

## 11. 配置文件（grid_strategy.yaml）最小字段集合

> 目标：参数集中管理、可回放、可灰度。  
> 说明：初始值建议偏保守，跑通回放后再调优。

### 11.1 交易与交易所
- `symbol`
- `exchange`
- `market_type`（spot/perp）
- `quote_ccy`

### 11.2 交易员输入（运行时可更新）
- `outer_range_low`
- `outer_range_high`
- `trend_gate`（true/false）
- `allow_mild_bias`（true/false）
- `mild_bias_cap`（例如 0.20：允许净敞口不超过 20% MAX_INVENTORY）

### 11.3 风控阈值
- `MAX_INVENTORY`
- `inv_warn=0.55`
- `inv_damage=0.70`
- `inv_stop=0.85`
- `inv_back_to_normal=0.40`
- `margin_cap`
- `max_dd`

### 11.4 Zone 参数
- `T_zone=48h`
- `T_window=48h`
- `bin_size`
- `zone_cover=0.65`
- `zone_change_threshold=0.10`
- `w1,w2,w3`（adv_score 权重）

### 11.5 Grid 参数
- `bar_tf`（1m/5m）
- `base_step_method`（ATR/RV）
- `core_compress_factor`
- `buffer_expand_factor`
- `N_buy_active`
- `M_sell_active`
- `edge_band`
- `edge_decay_factor`
- `refresh_delay_ms`（NORMAL）
- `refresh_delay_ms_defensive`（DEFENSIVE：通常更慢或关闭补单）

### 11.6 Skew 参数
- `inv_skew_max=0.40`
- `skew_max=0.25`

### 11.7 DeRisk 参数
- `cycle_efficiency_drop_threshold`
- `breakeven_flat_threshold`
- `opportunity_timeout=72h`
- `N_fail=3`

---

## 12. 运行时流程（主循环与控制循环）

### 12.1 trade_loop（事件驱动）

每次收到行情/成交回报：
1) **MarketData 更新**
- price, bar, fills, equity, margin, positions, open_orders

2) **计算关键风险量**
- inventory_ratio, inventory_slope
- breakeven_price
- margin_usage, liq_distance（若可得）

3) **RiskEngine（硬规则优先）**
- 若 Emergency 条件满足 → `EMERGENCY_STOP` 并执行紧急退出
- 若 inv_stop / risk_budget_stop → 切 `DAMAGE_CONTROL`

4) **StateMachine 更新**
- 根据 4.2 规则决定 state
- 输出允许行为集（权限矩阵）

5) **AdvantageEngine（轻量更新）**
- 更新必要的滚动统计缓存（bar_tf 粒度）
- 不在 trade_loop 做重计算（重计算放 control_loop）

6) **DeRiskEngine（快速判定）**
- 若处于 DeRisk 模式（或被触发）→ 下发降速指令（关闭 skew、收缩窗口等）

7) **GridEngine 生成目标订单集**
- NORMAL：维护双边网格、补单、撤换外层
- DEFENSIVE：冻结新增 buy、仅允许 sell 减仓、撤外层高风险 buy
- DAMAGE_CONTROL：reduce-only 分段减仓
- EMERGENCY_STOP：停止网格逻辑，执行紧急退出

8) **Execution 执行差量**
- desired_orders vs current_orders
- 下单/撤单/改单（幂等、重试、限频）

9) **Audit**
- state change / forced exit / emergency / re-anchor request / param update
- 写入 `audit_events.jsonl`

---

### 12.2 control_loop（4H/1D 定时）

每 4H（或 1D）执行：
1) OpportunityWindow 评估（5.1）
2) CoreZone 更新（5.2）
3) base_step / spacing 更新（ATR/RV）
4) DeRisk 评估（边际效率/机会衰减/house-money）
5) 写入 PARAM_UPDATE 审计事件（记录原因与快照）

---

---

## 13. 回测 / 回放（Backtest & Replay）实现规格

> 结论先行：**必须做回测/回放**，但 **v1 不需要 tick-level 历史数据**，也 **不需要另起炉灶搭一套全新的事件驱动框架**。  
> 正确做法是：复用同一套 `trade_loop`（事件驱动逻辑）与核心模块（StateMachine / RiskEngine / GridEngine / AdvantageEngine / Audit），仅替换 **数据源** 与 **执行层**，在 Replay 模式下回放历史路径。

### 13.1 回测的目标（Do / Don’t）

**Do（必须验证）**
1) **状态机与权限矩阵**是否严格生效：DEFENSIVE 是否冻结新增 buy，DAMAGE_CONTROL 是否强制 reduce-only，EMERGENCY_STOP 是否能中止网格并执行紧急退出。  
2) **硬风控触发器**是否在极端路径下确定触发：inventory stop / risk budget stop / structural stop / emergency stop。  
3) **机会窗口衰减与 DeRisk**是否按规则降速、收火、进入 Harvest-to-Exit。  
4) **Re-anchor 禁止条件**是否不可绕过：例如 `inventory_ratio > 0.60` 时必须拒绝 re-anchor 并写审计事件。  
5) **审计可复盘**：回放结束后，可以仅依赖 `audit_events.jsonl` 复原全部关键决策与状态迁移原因。

**Don’t（v1 刻意不追求）**
- 不追求 tick 级撮合精度与 queue position（没有盘口队列无法真实复现，反而制造“假精度”错觉）。
- 不做跨交易所路由/拆单优化回测（属于 execution optimization 的后期工作）。

### 13.2 数据粒度与回放事件模型

**历史数据最低要求（v1）**
- `bar_tf = 1m 或 5m` 的 OHLCV（至少 OHLC + volume）
- 若可得，补充：成交量分布、简单 mid/mark 价格（可选）

**为何不需要 tick-level（工程与策略一致性）**
- 本系统的关键决策点在 **bar 级统计 + 4H/1D control loop**；tick 只影响“某一格是否瞬间被扫”，不影响“风控与状态机是否会失效”。  
- tick 回放在缺乏真实订单簿队列、撮合优先级、盘口深度时，容易造成不真实的“高成交确定性”，误导风险评估。

**Replay 事件定义（最小集合）**
- `BAR_CLOSE`：每根 bar 结束时触发一次（用于滚动统计、risk 检查、轻量更新）
- `VIRTUAL_PRICE_TOUCH`：在 bar 内模拟触发某网格价位（用于 SimBroker 撮合）
- `FILL`：SimBroker 生成的成交事件（写入 fills，触发 trade_loop）
- `EXCHANGE_FAULT`：模拟断流/撤单失败/撮合异常（用于验证 EMERGENCY_STOP）

### 13.3 SimBroker（撮合与执行仿真）——保守模型

> 原则：宁可保守，不要乐观。回测应避免“把最坏路径成交假设成最好路径”。

**基础触发逻辑**
- 对某根 bar：
  - 若 `high >= sell_price` → sell limit 视为“有机会成交”
  - 若 `low <= buy_price` → buy limit 视为“有机会成交”

**同一根 bar 多层触发的处理**
- 采用 **保守顺序**（防止不现实的“瞬间扫全仓”）：
  - 先处理更靠近当前价的内层订单，再处理外层
  - 或限制 `max_fills_per_bar`（例如 1~3）
- 支持 `partial_fill_ratio`（例如 30%~70% 随机或固定），避免“每次都满成”。

**成本与摩擦**
- 必须计入：
  - 手续费（maker/taker 可配置，保守起见可按 taker 估）
  - 滑点（按 `slippage_bps` 或 `slippage_atr_mult`）
- 将摩擦纳入 `breakeven_price` 计算口径，保持与实盘一致。

**执行层行为一致性**
- Replay 模式下仍要走：
  - 幂等下单/撤单接口（只是落到 SimBroker）
  - 限频/重试逻辑（可模拟“成功/失败”并触发 EMERGENCY_STOP 测试）

### 13.4 ReplayMarketData（数据回放器）

实现一个 `ReplayMarketData`：
- 顺序读入历史 bar
- 每根 bar：
  1) 先发 `BAR_OPEN`（可选）
  2) 根据当前 active orders 生成 `VIRTUAL_PRICE_TOUCH`（可直接在 bar close 统一处理）
  3) 生成 `FILL` 事件并回调 trade_loop
  4) 最后发 `BAR_CLOSE` 给 trade_loop / control_loop 缓存

### 13.5 与“两循环”结构的结合（非常关键）

- `trade_loop`：在 Replay 中仍按事件驱动运行（FILL / BAR_CLOSE / FAULT）
- `control_loop`：在 Replay 中按历史时间推进：
  - 每累计满 4H（或 1D）bar → 执行一次 control_loop 逻辑：
    - OpportunityWindow 评估
    - CoreZone 更新
    - spacing 更新
    - DeRisk 评估与参数更新
  - 并写 `PARAM_UPDATE` 审计事件

> 这样做的好处：实盘与回放在“何时更新参数”的节奏上完全一致，避免回测与实盘逻辑漂移。

### 13.6 回测输出与验收（Replay DoD）

**输出物（必须）**
- `audit_events.jsonl`：结构性事件、状态迁移、参数更新、re-anchor 请求与拒绝原因（必须带 snapshot）
- `fills.parquet / csv`：成交记录（用于复核 inventory、breakeven、PnL）
- `state_store.json`：最终可恢复状态（断电恢复测试）
- `metrics_store.parquet`：关键时间序列（inventory_ratio, breakeven, margin_usage, state）

**验收标准（必须通过）**
1) 任意时刻新增订单行为必须遵守状态权限矩阵（见 4.1）。  
2) `inventory_ratio` 越过阈值时，状态机与 RiskEngine 必须在预期事件内触发并采取动作（撤单/冻结/减仓）。  
3) `inventory_ratio > 0.60` 时发起 re-anchor 必须被拒绝，且写审计事件。  
4) 模拟断流/撤单失败等 fault 时，必须进入 EMERGENCY_STOP 并停止网格逻辑。  
5) 仅依赖审计日志即可复原关键决策链路（why/when/what）。

### 13.7 分阶段建议（避免工程过度）

- **Phase 1（规则回放）**：用 bar + 保守 SimBroker，优先验证风控/状态机/参数更新节奏。  
- **Phase 2（执行摩擦敏感性）**：做滑点/手续费/partial fill 的敏感性分析。  
- **Phase 3（可选：tick/盘口）**：只有在明确要做 execution optimization（盘口深度、队列位置、拆单）时才考虑；不作为 v1 前置条件。


## 14. 测试用例（必须具备）

> 没有这些测试，系统会“能跑但跑错”，上线风险极高。

### 13.1 状态机测试（最高优先级）

- Case A：价格触边 → 必须进入 DEFENSIVE；新增 buy 必须被禁用
- Case B：inventory_ratio = 0.86 → 必须进入 DAMAGE_CONTROL；re-anchor 必须禁用；reduce-only 为真
- Case C：模拟 gap/断流 → 必须进入 EMERGENCY_STOP；所有网格逻辑停止；触发紧急退出

### 13.2 Core Zone 测试

- 用固定历史数据回放，确保：
  - core_zone 覆盖 >= 65% fill_density
  - 4H 内不会频繁抖动（zone_change_threshold 生效）
  - core_zone 始终位于 outer_range 内

### 13.3 DeRisk 测试

- 当 cycle_efficiency 下降或 breakeven 改善变平：
  - skew 必须关闭
  - active window 必须收缩
  - 进入 Harvest-to-Exit（或 DeRisk 标志为真）

### 13.4 Re-anchor 测试

- inventory_ratio > 0.60 时：
  - re-anchor 请求必须被拒绝，并记录审计事件
- inventory_ratio 降到 0.45 后：
  - re-anchor 才允许进入待执行流程（仍需记录）

---

## 15. 交付包建议（最小可交付）

你把以下三样交给程序员，他可以直接开工：

1) 你的制度文档（Part A/B/C：治理、策略逻辑、风控执行）
2) 本文档：`docs/engineering/GridSystem_Spec_v1.md`
3) 初始配置：`config/grid_strategy.yaml`（保守参数）

建议开发里程碑（v1）：
- M1：完成状态机 + RiskEngine + Execution（能按状态限制下单）
- M2：完成 GridEngine（NORMAL/DEFENSIVE/DAMAGE_CONTROL 行为一致）
- M3：完成 AdvantageEngine（OpportunityWindow + CoreZone）
- M4：完成 SkewEngine + DeRiskEngine（进攻增强与风险回收）
- M5：完成审计与回放测试（jsonl + 回放脚本）

---

## 附：实现注意事项（强约束）

- 任何时刻都必须有明确的退出路径（reduce-only / forced exit）
- 参数变化必须慢（4H/1D），执行反应可以快（事件驱动）
- DEFENSIVE 是强制状态：不得跳过
- inventory 是第一风险变量：PnL 与 inventory 冲突时，以 inventory 为最高优先级
- 所有结构性事件必须写入审计日志并保存 snapshot
