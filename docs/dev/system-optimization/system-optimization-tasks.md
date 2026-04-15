---
feature: system-optimization
phase: tasks
complexity: complex
generated_by: spec-dev
generated_at: 2026-04-14T00:00:00+08:00
version: 1
---

# 任务拆分: A股量化系统实战优化

## 执行分组

### Group 1: 权限修复 + 配置更新 (P0, 可并行)

#### Task 1.1: 修复 veto_filter 新增创业板过滤
- **文件:** `engine/t1_v4/veto_filter.py`
- **改动:**
  1. `DEFAULT_PARAMS` 新增 `excluded_prefixes: ["688", "300", "8", "4"]`
  2. 规则 3 改为循环检查 `excluded_prefixes`，替换现有硬编码
  3. 添加前缀到可读名称的映射 dict
- **验证:** 单元测试 — 300xxx 被拒绝，60xxxx/00xxxx/002xxx 通过
- **预计改动:** ~30 行

#### Task 1.2: 更新全局配置 (config.py + docker-compose.yml)
- **文件:** `app/config.py`, `docker-compose.yml`
- **改动:**
  1. `T1_TOP_N`: 5→2
  2. `T1_MARKET_SAFE_THRESHOLD`: 0.0→8.0
  3. `T1_MIN_TOTAL_SCORE`: 40.0→55.0
  4. 新增 `T1_EXCLUDED_PREFIXES`
  5. 新增 R3 卖出引擎配置项 (5项)
  6. 新增 R4 仓位管理配置项 (7项)
  7. docker-compose.yml 同步更新环境变量
- **验证:** 服务启动不报错，配置值正确加载
- **预计改动:** ~40 行

### Group 2: 评分权重调整 (P0)

#### Task 2.1: 调整资金面评分 (25→30)
- **文件:** `engine/t1_v4/capital_scorer.py`
- **改动:**
  1. `main_inflow`: fp 终点 10→12, 中间 3→3.6
  2. `turnover_score`: fp 峰值 5→6
  3. `continuous_inflow`: fp = [0, 1.8, 3.6, 6.0]
  4. `north_fund`: 基础分 3→3.6，满分 5→6
  5. 默认值（数据缺失时）等比调整
- **验证:** 单元测试 — 满分输入返回 30，边界值正确
- **预计改动:** ~20 行

#### Task 2.2: 调整基本面评分 (15→8)
- **文件:** `engine/t1_v4/fundamental_scorer.py`
- **改动:**
  1. `roe_score`: fp = [0.0, 1.2, 3.0]
  2. `profit_growth`: fp = [0.0, 1.2, 3.0]
  3. `pe_reasonable`: fp = [0.0, 0.8, 2.0, 2.0, 0.8, 0.0]
  4. 默认值等比调整 (2.0→1.0, 2.5→1.0)
- **验证:** 单元测试 — 满分输入返回 8
- **预计改动:** ~15 行

#### Task 2.3: 调整板块面评分 (15→17)
- **文件:** `engine/t1_v4/sector_scorer.py`
- **改动:**
  1. `rank_score`: fp = [9.0, 9.0, 3.4, 0.6, 0.0]
  2. `limit_up_score`: fp = [0.0, 1.9, 3.8, 5.0]
  3. 默认值调整 (4.0→4.5)
- **验证:** 单元测试 — 满分输入返回 17
- **预计改动:** ~10 行

#### Task 2.4: 更新 scorer 主模块
- **文件:** `engine/t1_v4/scorer.py`
- **改动:**
  1. `DEFAULT_CONFIG`: top_n=2, min_total_score=55.0
  2. `StockScore` 注释更新: capital 0-30, fundamental 0-8, sector 0-17
  3. `_empty_scores()` 注释更新
- **验证:** 代码注释与实际权重一致
- **预计改动:** ~10 行

### Group 3: 卖出引擎调优 (P1)

#### Task 3.1: 调整卖出引擎参数
- **文件:** `engine/t1_v4/sell_engine_v2.py`
- **改动:**
  1. `__init__` 默认参数:
     - phase1_stop_loss: -0.02 → -0.03
     - phase2_take_profit: 0.03 → 0.05
     - phase2_stop_loss: -0.02 → -0.03
     - phase3_stop_loss: -0.015 → -0.025
  2. 从 config 读取参数（如果 config 中有定义）
- **验证:** 单元测试 — 各阶段触发条件与新阈值一致
- **预计改动:** ~15 行

### Group 4: 仓位管理 (P1)

#### Task 4.1: 新建 PositionManager 模块
- **文件:** `engine/t1_v4/position_manager.py` (新建)
- **内容:**
  1. `PositionAdvice` 数据类
  2. `PositionManager` 类
  3. `allocate()` 方法 — 核心仓位分配逻辑
  4. `_check_drawdown_pause()` — 回撤暂停检查
  5. `_check_consecutive_loss()` — 连续亏损检查
  6. `_calc_quantity()` — 计算整手数（100股）
- **验证:** 单元测试 — 各种场景仓位分配正确
- **预计改动:** ~150 行（新文件）

#### Task 4.2: 集成仓位管理到 T1 服务
- **文件:** `app/services/t1_service.py`
- **改动:**
  1. `scan_candidates()` 末尾调用 `PositionManager.allocate()`
  2. 将仓位建议写入 t1_candidates 记录
  3. 需要查询近期 t1_trades（用于连续亏损判断）
  4. 需要查询模拟账户余额（用于金额计算）
- **依赖:** Task 4.1, Task 5.2 (DB 迁移)
- **预计改动:** ~40 行

### Group 5: 多策略共振 (P1)

#### Task 5.1: 新建共振检测模块
- **文件:** `engine/t1_v4/resonance.py` (新建)
- **内容:**
  1. `ResonanceResult` 数据类
  2. `ResonanceDetector` 类
  3. `detect()` 方法 — 对单只股票运行其他策略
  4. `BONUS_MAP` — 共振加分映射
- **验证:** 单元测试 — 加分逻辑正确
- **预计改动:** ~100 行（新文件）

#### Task 5.2: 数据库迁移 — t1_candidates 新增字段
- **操作:**
  1. 创建 Alembic 迁移脚本
  2. t1_candidates 新增: suggested_pct, suggested_quantity, position_reason, resonance_count, resonance_bonus, resonating_strategies
  3. 更新 `app/models/pg_models.py` 中的 T1Candidate 模型
- **预计改动:** ~30 行迁移 + ~10 行模型

#### Task 5.3: 集成共振到 T1 评分引擎
- **文件:** `engine/t1_v4/scorer.py`, `app/services/t1_service.py`
- **改动:**
  1. `T1V4Scorer.__init__` 初始化 `ResonanceDetector`
  2. `rank_and_select()` 中评分后、排序前执行共振检测
  3. 共振结果写入 StockScore.details
  4. t1_service 保存共振数据到 DB
- **依赖:** Task 5.1, Task 5.2
- **预计改动:** ~30 行

### Group 6: 自动化 + API (P2)

#### Task 6.1: 调整定时任务 + 每日报告 API
- **文件:** `app/routers/scheduler.py`, `app/routers/t1_strategy.py`, `app/services/t1_service.py`
- **改动:**
  1. t1_scan cron: "30 14" → "30 15"（收盘后扫描）
  2. t1_service 新增 `generate_daily_report()` 方法
  3. t1_strategy 新增 `GET /report` 端点
  4. 报告包含: 候选 + 5 维评分 + 共振状态 + 仓位建议 + 风控状态
- **依赖:** Group 4, Group 5
- **预计改动:** ~60 行

---

## 执行顺序

```
Group 1 (权限+配置)  ──┐
                       ├──→ Group 2 (评分权重) ──→ Group 3 (卖出引擎)
                       │
                       └──→ Group 5.2 (DB迁移)
                                    │
Group 4.1 (仓位模块)  ─────────────┤
Group 5.1 (共振模块)  ─────────────┤
                                    │
                                    ├──→ Group 5.3 (集成共振)
                                    ├──→ Group 4.2 (集成仓位)
                                    │
                                    └──→ Group 6 (自动化+API)
```

## 总估算

| 分组 | 任务数 | 新增/改动行数 | 优先级 |
|------|--------|--------------|--------|
| Group 1 | 2 | ~70 行 | P0 |
| Group 2 | 4 | ~55 行 | P0 |
| Group 3 | 1 | ~15 行 | P1 |
| Group 4 | 2 | ~190 行 | P1 |
| Group 5 | 3 | ~170 行 | P1 |
| Group 6 | 1 | ~60 行 | P2 |
| **合计** | **13** | **~560 行** | |
