---
feature: a-share-trading-redesign
created: 2026-04-07
---

# 任务列表

## Task 1: 创建 engine/ashare_rules.py 核心规则引擎
- AShareFeeCalculator（含印花税、过户费、最低佣金5元）
- ASharePriceValidator（涨跌停价格、股票类型判断）
- AShareCalendar（交易时间、节假日2025-2026）
- AShareLotValidator（100股/手校验）

## Task 2: 创建 tests/test_ashare_rules.py 单元测试
- 覆盖所有规则类的核心路径（9条用例）

## Task 3: 修改 app/models/pg_models.py + 新增 migration
- PaperPosition 增加 available_quantity / locked_quantity / locked_date
- 新建 alembic migration 文件

## Task 4: 创建 app/core/trading_rules.py 规则适配器
- TradingRuleEngine（集成校验）
- T+1 解锁逻辑

## Task 5: 修改 app/routers/paper_trading.py
- 注入 TradingRuleEngine
- 修复费用计算（买卖分别使用正确费率）
- T+1 锁仓：买入时设置 locked_quantity，卖出时校验 available_quantity

## Task 6: 修改 engine/t1_sell_engine.py
- SmartSellEngine 接受 stock_type 参数
- 动态设置 limit_up_pct

## Task 7: 修改 engine/t1_filters.py
- StockPoolFilter.is_eligible() 增加 is_suspended 参数

## Task 8: 修改 engine/t1_backtest.py
- 使用 AShareFeeCalculator 替换硬编码 fee_rate
