# Quant Platform v8 - A 股智能量化选股平台

多 Agent 协作的 A 股量化选股平台，基于 LangGraph 工作流引擎，集成 DeepSeek 大模型进行多维度股票分析。

## 技术栈

- **后端**: FastAPI + SQLAlchemy (async) + LangGraph
- **前端**: Vue 3 + TypeScript + Element Plus + ECharts
- **数据库**: PostgreSQL + MongoDB + Redis
- **LLM**: DeepSeek (OpenAI 兼容接口)
- **数据源**: Tushare / AKShare / BaoStock (三级降级)
- **部署**: Docker Compose

## 核心功能

### 多 Agent 智能分析
- 4 个分析师 Agent（技术面/基本面/新闻面/情绪面）
- 多空辩论机制（Bull/Bear Researcher）
- 风险评估（保守/平衡/激进三种风格）
- LangGraph 9 节点顺序工作流

### 量化策略引擎
- 5 大核心策略：趋势跟踪、均值回归、动量、量价、突破
- 策略自动发现与注册（StrategyRegistry）
- 多策略信号聚合与共振检测
- 策略健康度评估与分级

### 回测与模拟盘
- 历史数据回测（收益率/最大回撤/胜率/夏普比率）
- 模拟盘交易（买入/卖出/持仓管理/手续费计算）

### 市场情绪与自进化
- 市场情绪指标（0-100 综合评分）
- AESE 自进化引擎（策略权重自动调优）
- 定时任务调度（数据同步/情绪计算/推荐生成）

## 项目结构

```
quant-platform-v8/
├── app/                    # FastAPI 应用
│   ├── main.py            # 入口 + 中间件
│   ├── config.py          # 配置管理
│   ├── core/              # 数据库连接
│   ├── models/            # SQLAlchemy 模型 (10 张表)
│   └── routers/           # API 路由 (13 个模块)
├── agents/                # LLM Agent 系统
│   ├── analysts/          # 4 个分析师
│   ├── researchers/       # 多空研究员
│   ├── managers/          # 研究经理
│   ├── risk/              # 风控 Agent
│   ├── graph/             # LangGraph 工作流
│   └── llm/               # LLM 适配器
├── dataflows/             # 数据流
│   ├── providers/         # 3 个数据源提供者
│   └── source_manager.py  # 数据源管理器 + 缓存
├── engine/                # 策略引擎
│   ├── base.py            # 策略基类
│   ├── registry.py        # 策略注册表
│   ├── strategies/        # 5 个策略实现
│   └── signal_aggregator.py
├── frontend/              # Vue 3 前端
│   └── src/
│       ├── views/         # 8 个页面
│       ├── components/    # K 线图组件
│       └── api/           # API 客户端
├── docker/                # Docker 配置
├── tests/                 # 集成测试
└── docker-compose.yml
```

## 快速开始

### 环境要求
- Python 3.11+
- Node.js 18+
- PostgreSQL 15+, MongoDB 7+, Redis 7+

### 本地开发

```bash
# 1. 安装后端依赖
pip install -r requirements.txt

# 2. 配置环境变量
cp .env.example .env
# 编辑 .env 填入 DEEPSEEK_API_KEY, TUSHARE_TOKEN 等

# 3. 初始化数据库
alembic upgrade head

# 4. 启动后端
uvicorn app.main:app --reload --port 8000

# 5. 安装前端依赖
cd frontend && npm install

# 6. 启动前端
npm run dev
```

### Docker 部署

```bash
docker-compose up -d
```

访问 http://localhost (Nginx 反向代理)

## API 概览

| 模块 | 路径 | 说明 |
|------|------|------|
| 健康检查 | `/api/health` | 服务状态 + 指标 |
| 认证 | `/api/auth/*` | JWT 登录/注册 |
| 股票数据 | `/api/stocks/*` | 行情查询/同步 |
| 智能分析 | `/api/analysis/*` | 多 Agent 分析 + SSE |
| 每日推荐 | `/api/recommend/*` | 策略推荐 |
| 策略回测 | `/api/backtest/*` | 历史回测 |
| 模拟盘 | `/api/paper/*` | 模拟交易 |
| 市场情绪 | `/api/emotion/*` | 情绪指标 |
| 策略管理 | `/api/strategy/*` | 健康评估 |
| 自进化 | `/api/aese/*` | 策略权重调优 |
| 配置 | `/api/config/*` | 系统配置 |
| 调度 | `/api/scheduler/*` | 定时任务 |

## 运行测试

```bash
pip install pytest httpx anyio
pytest tests/ -v
```

## 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `DATABASE_URL` | PostgreSQL 连接 | `postgresql+asyncpg://...` |
| `MONGODB_URL` | MongoDB 连接 | `mongodb://localhost:27017` |
| `REDIS_URL` | Redis 连接 | `redis://localhost:6379` |
| `DEEPSEEK_API_KEY` | DeepSeek API Key | - |
| `DEEPSEEK_MODEL` | 模型名称 | `deepseek-chat` |
| `TUSHARE_TOKEN` | Tushare Token | - |
| `TUSHARE_ENABLED` | 启用 Tushare | `false` |

## License

MIT
