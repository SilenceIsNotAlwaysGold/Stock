---
feature: system-optimization
phase: design
complexity: complex
generated_by: spec-dev
generated_at: 2026-04-14T00:00:00+08:00
version: 1
---

# 技术设计: A股量化系统实战优化

## 1. 设计总览

### 改动范围

```
engine/t1_v4/veto_filter.py        ← R1: 新增 300xxx 过滤
engine/t1_v4/capital_scorer.py     ← R2: 权重 25→30
engine/t1_v4/fundamental_scorer.py ← R2: 权重 15→8
engine/t1_v4/sector_scorer.py      ← R2: 权重 15→17
engine/t1_v4/scorer.py             ← R2: 更新注释 + _empty_scores
engine/t1_v4/sell_engine_v2.py     ← R3: 调整止盈止损参数
engine/t1_v4/position_manager.py   ← R4: 新建仓位管理模块
engine/t1_v4/resonance.py          ← R5: 新建共振评分模块
app/config.py                      ← R1-R6: 新增配置项
app/services/t1_service.py         ← R4+R5: 集成仓位管理和共振
app/routers/t1_strategy.py         ← R4+R6: API 更新
app/routers/scheduler.py           ← R6: 调整扫描时间
docker-compose.yml                 ← 环境变量更新
```

### 不改动的模块

- `tech_scorer.py` — 技术面 30 分保持不变，已经合理
- `market_scorer.py` — 大盘面 15 分保持不变
- `agents/` — AI 分析不在本轮优化范围
- 前端 Vue 组件 — 仅后端逻辑变更（前端自动适配 API 返回值）

---

## 2. R1: 交易权限硬过滤

### 设计方案

**文件:** `engine/t1_v4/veto_filter.py`

在规则 3（科创板/北交所检查）后新增创业板过滤：

```python
# ---- 规则 3：科创板 / 北交所 / 创业板 ----------------------------------
code = ts_code.split(".")[0] if "." in ts_code else ts_code
if code.startswith("688"):
    result.passed = False
    result.reject_reasons.append("科创板（688xxx）")
    return result
if code.startswith("8") or code.startswith("4"):
    result.passed = False
    result.reject_reasons.append("北交所（8xxx/4xxx）")
    return result
# 新增：创业板过滤
if code.startswith("300"):
    result.passed = False
    result.reject_reasons.append("创业板（300xxx）")
    return result
```

**配置化:** 在 `app/config.py` 新增可配置的排除板块列表：

```python
# 交易权限配置 — 排除的股票代码前缀
T1_EXCLUDED_PREFIXES: list = ["688", "300", "8", "4"]
```

**改造 veto_filter:** 将硬编码的前缀检查改为从配置读取：

```python
DEFAULT_PARAMS = {
    ...
    "excluded_prefixes": ["688", "300", "8", "4"],  # 可配置
}

# 在 check() 方法中：
for prefix in self.params["excluded_prefixes"]:
    if code.startswith(prefix):
        result.passed = False
        # 根据前缀给出可读原因
        label = {"688": "科创板", "300": "创业板", "8": "北交所", "4": "北交所"}.get(prefix, prefix)
        result.reject_reasons.append(f"{label}（{prefix}xxx）")
        return result
```

---

## 3. R2: 评分权重重分配

### 权重变更总览

| 维度 | 原权重 | 新权重 | 变化 | 理由 |
|------|--------|--------|------|------|
| 技术面 | 30 | 30 | 不变 | 短线核心指标，已合理 |
| 资金面 | 25 | 30 | +5 | 主力资金对短线最关键 |
| 基本面 | 15 | 8 | -7 | ROE/PE 对 T+1 几乎无影响 |
| 板块面 | 15 | 17 | +2 | 板块轮动是 A 股特色 |
| 大盘面 | 15 | 15 | 不变 | 安全门控作用，不宜调 |
| **合计** | **100** | **100** | **0** | |

### 3.1 资金面评分 (25→30)

**文件:** `engine/t1_v4/capital_scorer.py`

| 子项 | 原分值 | 新分值 |
|------|--------|--------|
| 主力净流入 | 0-10 | 0-12 |
| 换手率 | 0-5 | 0-6 |
| 连续流入 | 0-5 | 0-6 |
| 北向资金 | 0-5 | 0-6 |
| **合计** | **0-25** | **0-30** |

**改动点:**
- `main_inflow`: np.interp fp 终点 10→12，中间点 3→3.6
- `turnover_score`: np.interp fp 峰值 5→6
- `continuous_inflow`: np.interp fp = [0, 1.8, 3.6, 6.0]
- `north_fund`: 基础分 3→3.6，满分 5→6
- 返回字段名不变 `capital_total`

### 3.2 基本面评分 (15→8)

**文件:** `engine/t1_v4/fundamental_scorer.py`

| 子项 | 原分值 | 新分值 |
|------|--------|--------|
| ROE 评分 | 0-5 | 0-3 |
| 利润增长 | 0-5 | 0-3 |
| PE 合理性 | 0-5 | 0-2 |
| **合计** | **0-15** | **0-8** |

**改动点:**
- `roe_score`: np.interp fp = [0.0, 1.2, 3.0]
- `profit_growth`: np.interp fp = [0.0, 1.2, 3.0]
- `pe_reasonable`: np.interp fp = [0.0, 0.8, 2.0, 2.0, 0.8, 0.0]
- 默认值（数据缺失时）同比例缩小

### 3.3 板块面评分 (15→17)

**文件:** `engine/t1_v4/sector_scorer.py`

| 子项 | 原分值 | 新分值 |
|------|--------|--------|
| 板块排名 | 0-8 | 0-9 |
| 涨停数量 | 0-4 | 0-5 |
| 连续强势 | 0-3 | 0-3 |
| **合计** | **0-15** | **0-17** |

**改动点:**
- `rank_score`: np.interp fp = [9.0, 9.0, 3.4, 0.6, 0.0]
- `limit_up_score`: np.interp fp = [0.0, 1.9, 3.8, 5.0]
- `consecutive_strong`: 保持不变（0-3）

### 3.4 Scorer 主模块更新

**文件:** `engine/t1_v4/scorer.py`

```python
DEFAULT_CONFIG = {
    "top_n": 2,                      # 5→2: 集中持仓
    "market_safe_threshold": 8.0,    # 保持不变
    "min_total_score": 55.0,         # 50→55: 提高门槛
}
```

- 更新 `_empty_scores()` 中的注释（文档性）
- 更新 `StockScore` 类的注释

### 3.5 Config 更新

**文件:** `app/config.py`

```python
T1_TOP_N: int = 2                       # 5→2
T1_MARKET_SAFE_THRESHOLD: float = 8.0   # 0.0→8.0（启用安全门）
T1_MIN_TOTAL_SCORE: float = 55.0        # 40→55
```

---

## 4. R3: 卖出引擎参数调整

### 设计方案

**文件:** `engine/t1_v4/sell_engine_v2.py`

| 参数 | 原值 | 新值 | 理由 |
|------|------|------|------|
| phase1_take_profit | 0.05 (5%) | 0.05 | 不变，高开锁利合理 |
| phase1_stop_loss | -0.02 (-2%) | -0.03 (-3%) | 主板低开-2%常见，给更多空间 |
| phase2_take_profit | 0.03 (3%) | 0.05 (5%) | 不急于止盈，让利润奔跑 |
| phase2_stop_loss | -0.02 (-2%) | -0.03 (-3%) | 减少被日内震荡洗出 |
| phase3_stop_loss | -0.015 (-1.5%) | -0.025 (-2.5%) | 同上 |
| limit_up_pct | 0.098 | 0.098 | 不变 |

**改动方式:** 仅修改 `__init__` 默认参数值，不改逻辑结构。

**额外改进:** 同时将参数可配置化，从 `app/config.py` 读取：

```python
# app/config.py 新增
T1_SELL_PHASE1_TAKE_PROFIT: float = 0.05
T1_SELL_PHASE1_STOP_LOSS: float = -0.03
T1_SELL_PHASE2_TAKE_PROFIT: float = 0.05
T1_SELL_PHASE2_STOP_LOSS: float = -0.03
T1_SELL_PHASE3_STOP_LOSS: float = -0.025
```

---

## 5. R4: 仓位管理模块

### 设计方案

**新建文件:** `engine/t1_v4/position_manager.py`

```python
@dataclass
class PositionAdvice:
    """仓位建议"""
    ts_code: str
    stock_name: str
    score: float
    suggested_pct: float       # 建议仓位百分比 (0.0-1.0)
    suggested_amount: float    # 建议金额
    suggested_quantity: int    # 建议股数（100的整数倍）
    reason: str                # 仓位决策原因

class PositionManager:
    """
    仓位管理器
    
    核心规则:
    1. 单只最大仓位 60%
    2. 选 2 只: 50% + 30%, 留 20% 现金
    3. 选 1 只: 60%, 留 40% 现金
    4. 连续亏损 3 次: 仓位减半
    5. 总回撤 >15%: 暂停 3 天
    6. 单日亏损 >5%: 预警
    """
    
    DEFAULT_CONFIG = {
        "max_single_pct": 0.60,         # 单只最大 60%
        "two_stock_pcts": [0.50, 0.30], # 双股分配
        "cash_reserve_pct": 0.20,       # 最低现金
        "consecutive_loss_limit": 3,     # 连续亏损次数
        "consecutive_loss_reduce": 0.50, # 降仓幅度
        "max_drawdown_pct": 0.15,       # 最大回撤
        "drawdown_pause_days": 3,        # 暂停天数
        "daily_loss_alert_pct": 0.05,   # 单日亏损预警
    }
```

**核心方法:**

```python
def allocate(
    self, 
    candidates: List[StockScore],  # 排序后的候选（最多2只）
    total_cash: float,             # 可用资金
    recent_trades: List[dict],     # 近期交易记录（判断连续亏损）
    account_stats: dict,           # 账户统计（判断回撤）
) -> List[PositionAdvice]:
    """
    计算仓位分配
    
    Returns:
        仓位建议列表，可能为空（暂停交易时）
    """
```

**决策流程:**

```
1. 检查回撤暂停 → 回撤>15%且未过冷静期 → 返回空列表
2. 检查连续亏损 → 近3笔全亏 → 仓位减半
3. 按候选数分配:
   - 0只: 返回空列表
   - 1只: 60% × 减仓系数
   - 2只: [50%, 30%] × 减仓系数
4. 按股价计算具体股数（100股整数倍）
5. 校验: 总仓位 + 现金 = 100%
```

**集成到 t1_service.py:**

在 `scan_candidates` 完成后，调用 `PositionManager.allocate()` 生成仓位建议，存入 `t1_candidates` 表的新字段 `suggested_pct` 和 `suggested_quantity`。

**数据库变更:** `t1_candidates` 表新增字段：
- `suggested_pct FLOAT` — 建议仓位比例
- `suggested_quantity INT` — 建议买入股数
- `position_reason VARCHAR(200)` — 仓位决策原因

---

## 6. R5: 多策略共振

### 设计方案

**新建文件:** `engine/t1_v4/resonance.py`

```python
@dataclass
class ResonanceResult:
    """共振检测结果"""
    ts_code: str
    resonance_count: int          # 共振策略数
    resonance_bonus: float        # 加分值
    resonating_strategies: List[str]  # 共振的策略名
    details: dict                 # 各策略信号详情

class ResonanceDetector:
    """
    多策略共振检测器
    
    将 T1 评分候选与其他量化策略信号交叉验证。
    共振加分规则:
    - 2个策略同时 BUY → +10 分
    - 3个以上策略同时 BUY → +15 分
    - 0-1个 → 不加分
    """
    
    BONUS_MAP = {
        0: 0.0,
        1: 0.0,
        2: 10.0,
        3: 15.0,   # 3个及以上都是+15
    }
```

**核心方法:**

```python
def detect(
    self,
    ts_code: str,
    daily_df: pd.DataFrame,
    context: dict = None,
) -> ResonanceResult:
    """
    对单只股票运行所有非T1策略，统计BUY信号数量。
    
    使用 StrategyRegistry 获取策略（排除 t1_overnight 类别），
    逐一运行，收集 action=BUY 的策略。
    """
```

**集成点:**

在 `scorer.py` 的 `rank_and_select()` 中，对通过基础评分的候选运行共振检测：

```python
# scorer.py rank_and_select() 中，在 step 5 排序之前:
# 5.1 共振加分（仅对通过基础筛选的候选）
if self.resonance_detector:
    for score in valid_scores:
        res = self.resonance_detector.detect(score.ts_code, daily_data.get(score.ts_code))
        score.total_score += res.resonance_bonus
        score.details["resonance_count"] = res.resonance_count
        score.details["resonance_bonus"] = res.resonance_bonus
        score.details["resonating_strategies"] = res.resonating_strategies
```

**注意:** 加分后总分可能超过 100（最高 115），这是设计允许的——共振是"超额加分"，用于拉开候选间的差距。

---

## 7. R6: 自动化工作流

### 设计方案

**文件:** `app/routers/scheduler.py`

调整扫描时间：

```python
# 原: "30 14 * * 1-5" (14:30)
# 改: "30 15 * * 1-5" (15:30 — 收盘后扫描，确保当日数据完整)
"t1_scan": {"name": "T1候选扫描", "cron": "30 15 * * 1-5", ...}
```

**文件:** `app/services/t1_service.py`

在 `scan_candidates()` 末尾新增每日报告生成：

```python
async def generate_daily_report(db, scan_date, candidates, position_advices):
    """
    生成每日扫描报告
    
    报告内容:
    - 扫描日期 + 大盘环境评分
    - Top 候选列表（含5维评分+共振状态+仓位建议）
    - 近期胜率统计
    - 风控状态（连续亏损/回撤情况）
    
    存储: 写入 t1_candidates 表 + 可通过 /api/t1/report 查询
    """
```

**文件:** `app/routers/t1_strategy.py`

新增 API：

```python
@router.get("/report")
async def get_daily_report(date: Optional[str] = None, db=Depends(get_db)):
    """获取每日扫描报告（含仓位建议和共振信息）"""
```

---

## 8. 数据库迁移

### 新增字段

**t1_candidates 表:**
```sql
ALTER TABLE t1_candidates ADD COLUMN suggested_pct FLOAT DEFAULT NULL;
ALTER TABLE t1_candidates ADD COLUMN suggested_quantity INT DEFAULT NULL;
ALTER TABLE t1_candidates ADD COLUMN position_reason VARCHAR(200) DEFAULT NULL;
ALTER TABLE t1_candidates ADD COLUMN resonance_count INT DEFAULT 0;
ALTER TABLE t1_candidates ADD COLUMN resonance_bonus FLOAT DEFAULT 0.0;
ALTER TABLE t1_candidates ADD COLUMN resonating_strategies TEXT DEFAULT NULL;
```

使用 Alembic 迁移。

---

## 9. 配置项汇总

### app/config.py 新增项

```python
# ===== R1: 交易权限 =====
T1_EXCLUDED_PREFIXES: list = ["688", "300", "8", "4"]

# ===== R2: 评分参数（已有项修改值）=====
T1_TOP_N: int = 2                       # 原5
T1_MARKET_SAFE_THRESHOLD: float = 8.0   # 原0.0
T1_MIN_TOTAL_SCORE: float = 55.0        # 原40.0

# ===== R3: 卖出引擎参数 =====
T1_SELL_PHASE1_TAKE_PROFIT: float = 0.05
T1_SELL_PHASE1_STOP_LOSS: float = -0.03
T1_SELL_PHASE2_TAKE_PROFIT: float = 0.05
T1_SELL_PHASE2_STOP_LOSS: float = -0.03
T1_SELL_PHASE3_STOP_LOSS: float = -0.025

# ===== R4: 仓位管理 =====
T1_MAX_SINGLE_PCT: float = 0.60
T1_TWO_STOCK_PCTS: list = [0.50, 0.30]
T1_CASH_RESERVE_PCT: float = 0.20
T1_CONSECUTIVE_LOSS_LIMIT: int = 3
T1_CONSECUTIVE_LOSS_REDUCE: float = 0.50
T1_MAX_DRAWDOWN_PCT: float = 0.15
T1_DRAWDOWN_PAUSE_DAYS: int = 3
```

### docker-compose.yml 新增环境变量

```yaml
T1_STRATEGY_TOP_N: "2"
T1_MIN_TOTAL_SCORE: "55.0"
T1_EXCLUDED_PREFIXES: "688,300,8,4"
```

---

## 10. 风险评估

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| 评分权重调整后选不出股 | 无候选推荐 | 回测验证，必要时微调 min_total_score |
| 止损放宽后单次亏损增大 | 收益波动 | 仓位管理补偿（连续亏损降仓） |
| 共振加分导致评分膨胀 | 排序失真 | 加分有上限（15分），且仅用于排序 |
| Tushare 积分不足 | 资金流/北向数据缺失 | 评分器有默认值兜底 |
| 主板池缩小后样本不足 | 选股范围受限 | 沪深主板+中小板约 3000+ 只，足够 |
