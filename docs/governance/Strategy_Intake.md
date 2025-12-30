# 策略立项表（Strategy Intake Form）

> 本文档是所有策略进入决策系统的**唯一入口**。  
> 所有策略必须先完成本表，才能进入后续评审流程  
>（PM / Quant / Execution / Portfolio / Stress / CRO / Platform）。

---

## 一、策略基本信息（Strategy Overview）

- 策略名称：
- 资产类别（当前：Crypto）：
- 交易标的（如 BTC/ETH/Alt / Perp / Spot / Options）：
- 交易周期（如 5m / 1h / 4h / Daily）：
- 策略类型（可多选）：
  - [ ] 趋势（Trend / Momentum）
  - [ ] 均值回归（Mean Reversion）
  - [ ] 套利（Arbitrage / Basis / Funding）
  - [ ] 做市 / 流动性提供（Market Making / Grid）
  - [ ] 其他（请说明）

---

## 二、交易逻辑描述（Trading Logic）

> 请用**可执行、可复述的语言**描述策略逻辑，避免模糊表述。

### 1. 入场逻辑（Entry）
- 入场条件：
- 信号来源（价格 / 技术指标 / 链上 / 事件）：

### 2. 出场逻辑（Exit）
- 止盈逻辑：
- 止损逻辑：
- 主动退出 / 被动退出条件：

### 3. 仓位管理（Position Sizing）
- 单笔仓位计算方式：
- 是否使用加仓 / 减仓逻辑：
- 最大单策略仓位限制：

### 4. 杠杆与保证金（Leverage & Margin）
- 是否使用杠杆：
- 最大杠杆倍数：
- 保证金管理方式：

### 5. 暂停 / 停机机制（If Any）
- 在什么情况下策略应暂停交易？
- 在什么情况下应完全停机？

---

## 三、风险结构标签（Risk Structure Tags）

> **必须勾选**，这是 Stress / Portfolio / CRO 的核心输入。

- [ ] 正凸性（Positive Convexity，如趋势策略）
- [ ] 负凸性（Negative Convexity，如网格 / short vol）
- [ ] 线性暴露（Linear Directional Exposure）
- [ ] 路径依赖损失（Path-Dependent Loss）
- [ ] 流动性依赖（Liquidity-Dependent Exit）

（如有特殊风险结构，请补充说明）

---

## 四、预期 Edge 说明（Expected Edge）

请回答以下问题（越具体越好）：

- 这个策略**为什么应该赚钱**？
- 利用的是什么市场低效或结构性特征？
- 是否依赖特定市场环境（regime）？
- 在什么环境下，这个 edge 会消失？

---

## 五、已知弱点与失败条件（Known Weaknesses）

> 请站在“反对者”的角度回答。

- 哪些市场状态对该策略最不利？
- 你认为这个策略**最可能怎么失败**？
- 是否存在你目前无法量化的风险？

---

## 六、回测与证据（Backtest / Evidence）

（如尚无，可留空，但需说明原因）

- 回测区间：
- 使用的数据源：
- 是否包含真实费用与滑点：
- 核心指标（Sharpe / Max DD / Win Rate）：
- 最大回撤发生在什么情景下？是否可解释？

---

## 七、执行假设（Execution Assumptions）

- 主要执行方式：
  - [ ] Maker
  - [ ] Taker
  - [ ] 混合
- 主要交易所（如 OKX / Binance / Bybit）：
- 手续费假设：
- 是否依赖 VIP 费率或返佣：

---

## 八、作者自我声明（Author Declaration）

> 以下问题**必须回答**，这是对策略负责的最低要求。

- 在什么情况下，你会**主动停止交易这个策略**？
- 什么事实或现象会**彻底推翻你的策略假设**？
- 如果只能选一个你最担心的风险，那是什么？

---

## 九、补充说明（Optional）

- 是否与现有策略存在高度相关性？
- 是否有尚未验证的假设？
- 任何你认为评审者必须知道的信息：

---

> **声明：**  
> 本策略作者确认以上信息真实、完整，  
> 并理解该策略将接受多角色（PM / Quant / Execution / Portfolio / Stress / CRO / Platform）的独立评审，  
> 且任何阶段均可能被否决或要求修改。
