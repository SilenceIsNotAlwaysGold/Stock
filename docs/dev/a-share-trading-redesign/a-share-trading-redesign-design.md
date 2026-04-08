---
feature: a-share-trading-redesign
complexity: complex
created: 2026-04-07
---

# 技术设计文档：A 股交易规则合规重设计

## 架构原则

1. **新增不替换**：新增 `engine/ashare_rules.py` 统一存放 A 股规则，现有文件最小化修改
2. **零依赖核心**：`AShareFeeCalculator`、`ASharePriceValidator`、`AShareCalendar` 均为纯函数/无状态类，不依赖数据库
3. **渐进增强**：paper_trading 通过调用规则层来增强，不重写路由逻辑
4. **回测分离**：回测中规则校验默认关闭（可选启用），避免影响性能

---

## 新增文件

### `engine/ashare_rules.py`（核心规则引擎）

```
AShareFeeCalculator      - 费用计算器
ASharePriceValidator     - 涨跌停价格校验
AShareCalendar           - 交易时间和节假日
AShareLotValidator       - 手数校验（100股/手）
```

所有类均为无状态，可直接 import 使用。

### `app/core/trading_rules.py`（API 层规则适配器）

```
TradingRuleEngine        - 集成所有规则，供 paper_trading router 调用
T1LockManager            - T+1 持仓锁定管理
```

---

## 修改文件

| 文件 | 修改内容 | 修改量 |
|------|---------|--------|
| `app/routers/paper_trading.py` | 注入规则校验，修复费用计算 | 中 |
| `app/models/pg_models.py` | PaperPosition 增加 T+1 字段 | 小 |
| `engine/t1_sell_engine.py` | ST股涨停参数化 | 小 |
| `engine/t1_filters.py` | 增加停牌过滤 | 小 |
| `engine/t1_backtest.py` | 使用 AShareFeeCalculator | 小 |
| `alembic/versions/` | 新增 migration | 小 |

---

## 详细设计

### 1. `engine/ashare_rules.py`

#### AShareFeeCalculator

```python
@dataclass
class FeeDetail:
    commission: float      # 佣金（买卖均有）
    stamp_duty: float      # 印花税（仅卖出）
    transfer_fee: float    # 过户费（仅沪市）
    total: float

class AShareFeeCalculator:
    MIN_COMMISSION = 5.0   # 最低佣金5元

    def __init__(self, commission_rate: float = 0.0003):
        self.commission_rate = commission_rate

    def calc_buy_fee(self, ts_code: str, amount: float) -> FeeDetail:
        commission = max(amount * self.commission_rate, self.MIN_COMMISSION)
        transfer_fee = amount * 0.00002 if ts_code.endswith(".SH") else 0.0
        return FeeDetail(commission=commission, stamp_duty=0.0,
                         transfer_fee=transfer_fee,
                         total=commission + transfer_fee)

    def calc_sell_fee(self, ts_code: str, amount: float) -> FeeDetail:
        commission = max(amount * self.commission_rate, self.MIN_COMMISSION)
        stamp_duty = amount * 0.001         # 印花税 0.1%
        transfer_fee = amount * 0.00002 if ts_code.endswith(".SH") else 0.0
        return FeeDetail(commission=commission, stamp_duty=stamp_duty,
                         transfer_fee=transfer_fee,
                         total=commission + stamp_duty + transfer_fee)
```

#### ASharePriceValidator

```python
class StockType(str, Enum):
    NORMAL = "normal"       # 主板，±10%
    ST = "st"               # ST/SST，±5%
    STAR = "star"           # 科创板688，±20%
    CHINEXT_REG = "chinext_reg"  # 创业板注册制，±20%

class ASharePriceValidator:
    @staticmethod
    def get_stock_type(ts_code: str, stock_name: str) -> StockType:
        code = ts_code.split(".")[0]
        if "ST" in stock_name.upper(): return StockType.ST
        if code.startswith("688"): return StockType.STAR
        # 创业板注册制：300xxx，2020年8月24日后上市
        return StockType.NORMAL

    @staticmethod
    def get_limit_pct(stock_type: StockType) -> float:
        return {StockType.ST: 0.05, StockType.STAR: 0.20,
                StockType.CHINEXT_REG: 0.20}.get(stock_type, 0.10)

    def calc_limit_prices(self, prev_close: float, stock_type: StockType):
        pct = self.get_limit_pct(stock_type)
        limit_up = round(prev_close * (1 + pct), 2)
        limit_down = round(prev_close * (1 - pct), 2)
        return limit_up, limit_down

    def validate_buy_price(self, price: float, limit_up: float) -> tuple[bool, str]:
        if price > limit_up:
            return False, f"买入价 {price} 超过涨停价 {limit_up}"
        return True, ""

    def validate_sell_price(self, price: float, limit_down: float) -> tuple[bool, str]:
        if price < limit_down:
            return False, f"卖出价 {price} 低于跌停价 {limit_down}"
        return True, ""
```

#### AShareCalendar

```python
class AShareCalendar:
    # 内置2025-2026年节假日（ISO格式）
    HOLIDAYS_2025_2026 = {
        "2025-01-01", "2025-01-28", ...,  # 完整节假日列表
    }

    MORNING_START = time(9, 30)
    MORNING_END   = time(11, 30)
    AFTERNOON_START = time(13, 0)
    AFTERNOON_END   = time(15, 0)

    @classmethod
    def is_trading_day(cls, d: date) -> bool:
        return d.weekday() < 5 and d.isoformat() not in cls.HOLIDAYS_2025_2026

    @classmethod
    def is_trading_time(cls, dt: datetime) -> bool:
        if not cls.is_trading_day(dt.date()): return False
        t = dt.time()
        return (cls.MORNING_START <= t <= cls.MORNING_END or
                cls.AFTERNOON_START <= t <= cls.AFTERNOON_END)
```

#### AShareLotValidator

```python
class AShareLotValidator:
    LOT_SIZE = 100  # 1手 = 100股

    @staticmethod
    def validate_buy_quantity(quantity: int) -> tuple[bool, str]:
        if quantity % AShareLotValidator.LOT_SIZE != 0:
            return False, f"买入数量必须为100的整数倍（1手=100股），当前: {quantity}"
        return True, ""

    @staticmethod
    def validate_sell_quantity(quantity: int, available: int) -> tuple[bool, str]:
        if quantity > available:
            return False, f"可卖数量不足（T+1规则），可卖: {available}，请求: {quantity}"
        return True, ""
```

---

### 2. `app/core/trading_rules.py`

```python
class TradingRuleEngine:
    """集成所有规则，供 paper_trading router 调用"""

    def __init__(self, commission_rate: float = 0.0003, skip_time_check: bool = False):
        self.fee_calc = AShareFeeCalculator(commission_rate)
        self.price_validator = ASharePriceValidator()
        self.lot_validator = AShareLotValidator()
        self.skip_time_check = skip_time_check

    def validate_order(self, req: PaperOrderRequest, position=None) -> list[str]:
        """返回错误列表，空列表表示通过"""
        errors = []
        # 1. 交易时间
        if not self.skip_time_check and not AShareCalendar.is_trading_time(datetime.now()):
            errors.append("非交易时间")
        # 2. 手数校验（买入）
        if req.direction == "BUY":
            ok, msg = self.lot_validator.validate_buy_quantity(req.quantity)
            if not ok: errors.append(msg)
        # 3. T+1 校验（卖出）
        if req.direction == "SELL" and position:
            ok, msg = self.lot_validator.validate_sell_quantity(
                req.quantity, position.available_quantity)
            if not ok: errors.append(msg)
        return errors

    def calc_fee(self, ts_code: str, direction: str, amount: float) -> FeeDetail:
        if direction == "BUY":
            return self.fee_calc.calc_buy_fee(ts_code, amount)
        return self.fee_calc.calc_sell_fee(ts_code, amount)
```

---

### 3. `app/models/pg_models.py` - PaperPosition 变更

```python
# 新增字段（向后兼容，有默认值）
available_quantity: Mapped[int] = mapped_column(Integer, default=0, comment="可卖数量(T+1解锁)")
locked_quantity: Mapped[int] = mapped_column(Integer, default=0, comment="T+1锁定数量")
locked_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True, comment="锁定日期")
```

**T+1 解锁逻辑**：在 `GET /api/paper/positions` 时，检查 `locked_date < today`，
若是则将 `locked_quantity` 合并到 `available_quantity`，自动解锁。

---

### 4. `engine/t1_sell_engine.py` - SmartSellEngine 修正

```python
# 修改前（硬编码）
DEFAULT_PARAMS = {
    "limit_up_pct": 0.098,
    ...
}

# 修改后（参数化）
def __init__(self, stock_type: StockType = StockType.NORMAL, **overrides):
    limit_pct = ASharePriceValidator.get_limit_pct(stock_type)
    self.params = {
        "limit_up_pct": limit_pct * 0.98,   # 略低于理论值，避免浮点误差
        "stop_loss_pct": -0.03,
        ...
        **overrides
    }
```

---

### 5. `engine/t1_filters.py` - 停牌过滤

```python
# StockPoolFilter.is_eligible() 增加参数
@staticmethod
def is_eligible(
    ts_code: str,
    stock_name: str,
    list_date: Optional[str] = None,
    min_list_days: int = 60,
    is_suspended: bool = False,     # 新增
) -> Tuple[bool, str]:
    if is_suspended:
        return False, "停牌中"
    # ... 原有逻辑不变
```

---

### 6. `engine/t1_backtest.py` - 费用修正

```python
# 修改前
fee_rate = 0.0003  # 万三
buy_cost = amount * fee_rate
sell_cost = amount * fee_rate

# 修改后
from engine.ashare_rules import AShareFeeCalculator
_fee_calc = AShareFeeCalculator()
buy_fee = _fee_calc.calc_buy_fee(ts_code, amount).total
sell_fee = _fee_calc.calc_sell_fee(ts_code, amount).total
```

---

### 7. Alembic Migration

新建 `alembic/versions/20260407_add_t1_lock_fields.py`，为 `paper_positions` 表新增：
- `available_quantity` INT NOT NULL DEFAULT 0
- `locked_quantity` INT NOT NULL DEFAULT 0
- `locked_date` DATE NULL

---

## 测试设计

新建 `tests/test_ashare_rules.py`，覆盖：

| 测试用例 | 断言 |
|---------|------|
| 沪市卖出10万，印花税100元，过户费2元 | `fee.stamp_duty == 100.0` |
| 深市买入5万，无过户费 | `fee.transfer_fee == 0.0` |
| 买入金额小，佣金保底5元 | `fee.commission == 5.0` |
| 买入150股，校验失败 | `errors 含 "100的整数倍"` |
| T+1 当日买入后卖出，校验失败 | `errors 含 "T+1锁仓"` |
| ST股涨停阈值为5% | `limit_pct == 0.05` |
| 科创板涨停阈值为20% | `limit_pct == 0.20` |
| 工作日9:30 是交易时间 | `is_trading_time() == True` |
| 工作日12:00 非交易时间 | `is_trading_time() == False` |

---

## 实施顺序（依赖关系）

```
Task 1: engine/ashare_rules.py（无依赖，核心）
    ↓
Task 2: tests/test_ashare_rules.py（依赖 Task 1）
    ↓
Task 3: app/models/pg_models.py + migration（T+1字段）
    ↓
Task 4: app/core/trading_rules.py（依赖 Task 1）
    ↓
Task 5: app/routers/paper_trading.py（依赖 Task 3, 4）
    ↓
Task 6: engine/t1_sell_engine.py（依赖 Task 1）
Task 7: engine/t1_filters.py（独立）
Task 8: engine/t1_backtest.py（依赖 Task 1）
```

Task 6、7、8 可并行。
