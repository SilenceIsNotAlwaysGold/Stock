---
feature: a-share-trading-redesign
complexity: complex
planning: each
execution: task
created: 2026-04-07
---

# 需求文档：A 股交易规则合规重设计

## 背景与问题

通过代码审查，现有交易系统存在以下 A 股规则不合规问题：

### 现状问题清单

| 问题 | 位置 | 严重度 |
|------|------|--------|
| 模拟盘未实施 T+1 锁仓，当日买入可当日卖出 | `app/routers/paper_trading.py:87` | 高 |
| 手续费仅收万三，缺少印花税(0.1%)和过户费(0.002%) | `app/routers/paper_trading.py:61` | 高 |
| 无涨跌停价格校验，可以超价下单 | `app/routers/paper_trading.py:56` | 高 |
| 无交易时间约束，24小时可下单 | `app/routers/paper_trading.py` | 中 |
| 无最小交易单位(100股/手)校验 | `app/routers/paper_trading.py:18` | 中 |
| 模拟账户存储在内存，重启丢失 | `app/routers/paper_trading.py:14` | 中 |
| T1 卖出引擎涨停阈值固定 9.8%，ST 股为 5% | `engine/t1_sell_engine.py:47` | 中 |
| 回测无印花税，收益率偏高 | `engine/t1_backtest.py` | 高 |
| 无停牌股票过滤 | `engine/t1_filters.py` | 中 |
| 集合竞价时间窗口仅用于止盈，未建模 9:15-9:25 申报期 | `engine/t1_sell_engine.py:55` | 低 |

---

## 功能需求

### FR-001：A 股交易费用计算器（核心）

**A 股完整费用结构**：

| 费用类型 | 收取方 | 费率 | 方向 | 说明 |
|---------|--------|------|------|------|
| 佣金 | 券商 | 万三(0.03%)，最低5元 | 买+卖 | 可配置 |
| 印花税 | 国家税务局 | 0.1% | 仅卖出 | A股特有，固定不可配 |
| 过户费 | 中登公司 | 0.002% | 买+卖 | 仅沪市(`.SH`)，深市免收 |
| 合计买入成本 | - | ≈0.032% | 买 | 沪市含过户费 |
| 合计卖出成本 | - | ≈0.132% | 卖 | 沪市含印花税+过户费 |

**接口设计**：
```python
class AShareFeeCalculator:
    def calc_buy_fee(self, ts_code: str, amount: float, commission_rate: float = 0.0003) -> FeeDetail
    def calc_sell_fee(self, ts_code: str, amount: float, commission_rate: float = 0.0003) -> FeeDetail

@dataclass
class FeeDetail:
    commission: float      # 佣金
    stamp_duty: float      # 印花税（买入为0）
    transfer_fee: float    # 过户费
    total: float           # 合计
```

### FR-002：T+1 持仓锁定引擎

**A 股 T+1 规则**：当日买入的股票，不可当日卖出，次日方可卖出。

**实现要求**：
- `PaperPosition` 增加 `available_quantity`（可卖数量）字段
- 每日开盘前（或第一次查询时），将 `locked_quantity` 解锁到 `available_quantity`
- 下单时校验：卖出数量 ≤ `available_quantity`，否则拒绝并返回 `T+1锁仓，明日可卖`

**数据模型变更**：
```python
class PaperPosition:
    quantity: int              # 持仓总数量
    available_quantity: int    # 可卖数量（T+1解锁后）
    locked_quantity: int       # T+1锁定数量（当日买入）
    locked_date: date          # 锁定日期
```

### FR-003：涨跌停价格校验

**A 股涨跌停规则**：
- 普通股（主板）：前收盘价 × ±10%
- ST 股：前收盘价 × ±5%
- 科创板/创业板注册制：前收盘价 × ±20%
- 新股首日：无涨跌停限制

**校验逻辑**：
- 买入价格 ≤ 涨停价，否则拒绝
- 卖出价格 ≥ 跌停价，否则拒绝
- 当日已涨停的股票，买入委托可能无法成交（涨停封板），需给出警告

**股票类型判断**（基于 `ts_code` 和 `stock_name`）：
```python
def get_limit_pct(ts_code: str, stock_name: str) -> float:
    if "ST" in stock_name: return 0.05
    if ts_code.startswith("688") or is_chinext_registration(ts_code): return 0.20
    return 0.10
```

### FR-004：交易时间校验

**A 股交易时间**：
```
集合竞价申报：9:15 - 9:25（可撤单）
集合竞价确认：9:25 - 9:30（不可撤单）
上午连续竞价：9:30 - 11:30
中午休市：11:30 - 13:00
下午连续竞价：13:00 - 15:00
收盘集合竞价：14:57 - 15:00（深市）
非交易日：周末、法定节假日
```

**校验要求**：
- 模拟盘下单校验当前时间，非交易时间返回 `{error: "非交易时间，当前时间 HH:MM，A股交易时间 9:30-11:30 / 13:00-15:00"}`
- 提供 `is_trading_time()` 工具函数，支持 `force=True` 参数绕过（回测/测试用）
- 节假日表从配置文件或系统配置表读取（初始内置2025-2026年节假日）

### FR-005：最小交易单位校验

**A 股规则**：买入以 100 股为最小单位（1手），卖出可以是任意数量（可卖零股）。

**校验**：
- 买入：`quantity % 100 == 0`，否则返回 `买入数量必须为100的整数倍（1手=100股）`
- 卖出：无此限制，允许卖出任意数量

### FR-006：回测引擎费用修正

**目标**：在所有回测脚本和引擎中，统一使用 `AShareFeeCalculator`，确保回测结果真实反映 A 股真实交易成本。

**影响文件**：
- `engine/t1_backtest.py`
- `engine/strategies/t1_final.py` 等所有含 fee/commission 计算的文件
- `scripts/t1_*_backtest.py` 所有回测脚本

**修正前后对比**（以10万买入为例）：
```
修正前：买入费用 30元，卖出费用 30元，总成本 60元（0.06%）
修正后：买入费用 52元，卖出费用 152元，总成本 204元（0.204%）
```

### FR-007：停牌股票过滤

**A 股停牌规则**：停牌股票不可交易。

**实现**：
- `StockPoolFilter.is_eligible()` 增加 `is_suspended: bool` 参数
- 停牌判断：`DailyBar` 表中对应日期记录不存在，或 `volume == 0`
- 回测时自动跳过停牌日期的交易

### FR-008：ST 股涨跌停修正

**问题**：`SmartSellEngine.DEFAULT_PARAMS["limit_up_pct"]` 固定为 `0.098`，ST 股实际涨停为 4.8%（5% 下取整精度）。

**修正**：`SmartSellEngine` 接受 `stock_type` 参数，动态设置 `limit_up_pct` 和 `stop_loss_pct`。

---

## 非功能需求

### NFR-001：向后兼容
- 所有修改须保持现有 API 接口不变（新增字段可选）
- `AShareFeeCalculator` 可单独使用，不强依赖其他模块

### NFR-002：可配置性
- 佣金费率可通过 `SystemConfig` 配置（key: `trading.commission_rate`）
- 节假日表可通过 API 更新
- 涨跌停校验可通过参数 `skip_price_check=True` 关闭（回测用）

### NFR-003：测试覆盖
- 每个 FR 需要对应单元测试
- 费用计算精度：误差 < 0.01元

---

## 不在范围内（Out of Scope）

- 北交所特殊交易规则（T+0 机制）
- 融资融券
- 期权/期货
- 实盘对接（仅模拟盘）
- 分时数据和逐笔交易

---

## 验收标准

- [ ] 模拟盘买入当日卖出，系统返回 T+1 锁仓错误
- [ ] 卖出 10万元沪市股票，手续费 = 佣金(30元) + 印花税(100元) + 过户费(2元) = 132元
- [ ] 超过涨停价买入，系统拒绝并提示
- [ ] 非交易时间下单，系统返回提示
- [ ] 买入 150 股，系统拒绝并提示必须为100的整数倍
- [ ] 回测结果中总费用相比修改前增加（更真实）
