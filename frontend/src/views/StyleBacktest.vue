<template>
  <div class="sb-page">
    <el-alert type="warning" :closable="false" show-icon style="margin-bottom:12px">
      <template #title>
        诚实风险拦截：以下每个风格均经 8 年逐年样本外 + 真实成本严格验证。
        判决标签为事实结论——除「打平被动」外均已被证伪/为陷阱，<b>勿被漂亮回测或战法话术误导</b>。
        详见仓库 STRATEGY_RESEARCH_VERDICT.md。
      </template>
    </el-alert>
    <!-- 风格选择 -->
    <el-card class="toolbar">
      <template #header><span>选择交易风格（含诚实判决）</span></template>
      <div class="style-cards">
        <div
          v-for="s in styles"
          :key="s.key"
          class="style-card"
          :class="{ active: selected === s.key }"
          @click="selected = s.key"
        >
          <div class="sc-top">
            <span class="sc-name">{{ s.name }}</span>
            <span class="verdict-badge" :style="verdictStyle(s.verdict)">
              {{ s.verdict }}
            </span>
          </div>
          <div class="sc-desc">{{ s.desc }}</div>
          <div class="sc-verdict" v-if="s.verdict_note">⚖ {{ s.verdict_note }}</div>
          <div class="sc-meta num">
            持仓 {{ s.target_hold_days }} 日 · TOP {{ s.top_n }}
          </div>
        </div>
      </div>

      <div class="param-row">
        <el-date-picker
          v-model="range"
          type="daterange"
          value-format="YYYY-MM-DD"
          range-separator="→"
          start-placeholder="开始日期"
          end-placeholder="结束日期"
          style="width: 300px"
        />
        <div class="cash-field">
          <span class="cash-lbl">初始资金</span>
          <el-input-number v-model="initialCash" :min="10000" :step="10000" :controls="false" style="width: 140px" />
        </div>
        <el-button type="primary" :loading="running" :disabled="!selected" @click="run">
          <el-icon><VideoPlay /></el-icon>&nbsp;{{ running ? '回测中...' : '运行回测' }}
        </el-button>
        <span class="hint">全市场回测约需 1-2 分钟，请耐心等待</span>
      </div>
      <el-progress
        v-if="running"
        :percentage="100"
        :indeterminate="true"
        :duration="2"
        status="success"
        :show-text="false"
        style="margin-top: 12px"
      />
    </el-card>

    <el-alert
      v-if="errorMsg"
      :title="errorMsg"
      type="error"
      show-icon
      :closable="false"
      style="margin-bottom: 16px"
    />

    <el-empty
      v-if="!running && !errorMsg && !result"
      description="选择风格与参数后点击「运行回测」"
      style="margin-top: 60px"
    />

    <template v-if="result && !errorMsg">
      <!-- 标题行 -->
      <div class="result-head">
        <div class="rh-title">
          <span class="rh-name">{{ result.style?.name }}</span>
          <span class="rh-desc">{{ result.style?.desc }}</span>
        </div>
        <div class="rh-tags">
          <el-tag effect="plain" class="num">{{ result.period }}</el-tag>
          <el-tag v-if="result.emotion_gated" type="warning" effect="dark">情绪周期 gating 已启用</el-tag>
        </div>
      </div>

      <!-- KPI 网格 -->
      <div class="kpi-grid">
        <div class="kpi glass">
          <div class="kpi-l">总收益</div>
          <div class="kpi-v num" :class="cls(result.total_return_pct)">{{ sign(result.total_return_pct) }}%</div>
        </div>
        <div class="kpi glass">
          <div class="kpi-l">年化收益</div>
          <div class="kpi-v num" :class="cls(result.annual_return_pct)">{{ sign(result.annual_return_pct) }}%</div>
        </div>
        <div class="kpi glass">
          <div class="kpi-l">最大回撤</div>
          <div class="kpi-v num down">{{ fmt(result.max_drawdown_pct) }}%</div>
        </div>
        <div class="kpi glass">
          <div class="kpi-l">夏普比率</div>
          <div class="kpi-v num">{{ fmt(result.sharpe_ratio) }}</div>
        </div>
        <div class="kpi glass">
          <div class="kpi-l">索提诺</div>
          <div class="kpi-v num">{{ fmt(result.sortino_ratio) }}</div>
        </div>
        <div class="kpi glass">
          <div class="kpi-l">胜率</div>
          <div class="kpi-v num">{{ fmt((result.win_rate ?? 0) * 100) }}%</div>
        </div>
        <div class="kpi glass">
          <div class="kpi-l">盈亏比</div>
          <div class="kpi-v num">{{ fmt(result.profit_factor) }}</div>
        </div>
        <div class="kpi glass">
          <div class="kpi-l">期望收益</div>
          <div class="kpi-v num" :class="cls(result.expectancy_pct)">{{ sign(result.expectancy_pct) }}%</div>
        </div>
        <div class="kpi glass">
          <div class="kpi-l">平均持仓</div>
          <div class="kpi-v num">{{ fmt(result.avg_holding_days) }} 日</div>
        </div>
        <div class="kpi glass">
          <div class="kpi-l">成本拖累</div>
          <div class="kpi-v num gold">{{ fmt(result.cost_drag_pct) }}%</div>
        </div>
        <div class="kpi glass">
          <div class="kpi-l">年换手</div>
          <div class="kpi-v num">{{ fmt(result.annual_turnover) }}</div>
        </div>
        <div class="kpi glass">
          <div class="kpi-l">评分 IC</div>
          <div class="kpi-v num">{{ fmt(result.score_ic, 3) }} / IR {{ fmt(result.score_icir, 2) }}</div>
        </div>
      </div>

      <!-- 保守实盘预期 callout -->
      <el-card class="callout">
        <div class="callout-head">
          <el-icon><WarningFilled /></el-icon>&nbsp;保守实盘预期
        </div>
        <div class="callout-body">
          <div class="cb-main num">
            预期实盘收益 ≈
            <span :class="cls(result.expected_live_return_pct)">{{ sign(result.expected_live_return_pct) }}%</span>
          </div>
          <div class="cb-sub num">
            = 回测总收益 {{ sign(result.total_return_pct) }}% × (1 − 衰减 {{ fmt((result.live_decay ?? 0) * 100) }}%)
          </div>
          <div class="cb-note">回测结果存在过拟合与执行衰减，实盘请以保守预期为锚，并结合下方诚实声明。</div>
        </div>
      </el-card>

      <!-- 资金曲线 + 事件研究 -->
      <el-row :gutter="16" style="margin-bottom: 16px">
        <el-col :span="15">
          <el-card>
            <template #header><span>资金曲线</span></template>
            <div ref="equityRef" style="width: 100%; height: 300px"></div>
          </el-card>
        </el-col>
        <el-col :span="9">
          <el-card>
            <template #header><span>事件研究 (T+1 ~ T+N)</span></template>
            <div ref="eventRef" style="width: 100%; height: 300px"></div>
          </el-card>
        </el-col>
      </el-row>

      <!-- 诚实声明 -->
      <el-card v-if="result.realism_notes?.length" class="realism">
        <template #header><span>⚠️ 现实化 / 诚实声明</span></template>
        <ul class="realism-list">
          <li v-for="(n, i) in result.realism_notes" :key="i">{{ n }}</li>
        </ul>
      </el-card>

      <!-- 月度收益 -->
      <el-card v-if="result.monthly_returns?.length" class="block-card">
        <template #header><span>月度收益</span></template>
        <el-table :data="result.monthly_returns" size="small" stripe>
          <el-table-column label="月份" prop="month" width="110" />
          <el-table-column label="交易数" prop="trades" width="90" />
          <el-table-column label="平均盈亏%" width="120">
            <template #default="{ row }">
              <span class="num" :class="cls(row.avg_pnl_pct)">{{ sign(row.avg_pnl_pct) }}%</span>
            </template>
          </el-table-column>
          <el-table-column label="合计盈亏%" width="120">
            <template #default="{ row }">
              <span class="num" :class="cls(row.total_pnl_pct)">{{ sign(row.total_pnl_pct) }}%</span>
            </template>
          </el-table-column>
          <el-table-column label="胜率%" width="100">
            <template #default="{ row }">
              <span class="num">{{ fmt((row.win_rate ?? 0) * 100) }}%</span>
            </template>
          </el-table-column>
        </el-table>
      </el-card>

      <!-- 最近交易 -->
      <el-card v-if="result.recent_trades?.length" class="block-card">
        <template #header>
          <span>最近交易（毛 / 净 / 成本，{{ result.total_trades }} 笔 · 胜 {{ result.win_count }} / 负 {{ result.loss_count }}）</span>
        </template>
        <el-table :data="result.recent_trades" size="small" stripe height="420">
          <el-table-column label="买入日" prop="buy_date" width="105" />
          <el-table-column label="卖出日" prop="sell_date" width="105" />
          <el-table-column label="代码" prop="ts_code" width="100" />
          <el-table-column label="名称" prop="stock_name" width="90" />
          <el-table-column label="买价" width="80">
            <template #default="{ row }"><span class="num">{{ row.buy_price?.toFixed(2) }}</span></template>
          </el-table-column>
          <el-table-column label="卖价" width="80">
            <template #default="{ row }"><span class="num">{{ row.sell_price?.toFixed(2) }}</span></template>
          </el-table-column>
          <el-table-column label="毛收益%" width="100" sortable prop="gross_pnl_pct">
            <template #default="{ row }">
              <span class="num" :class="cls(row.gross_pnl_pct)">{{ sign(row.gross_pnl_pct) }}%</span>
            </template>
          </el-table-column>
          <el-table-column label="成本%" width="90">
            <template #default="{ row }"><span class="num gold">{{ fmt(row.cost_pct) }}%</span></template>
          </el-table-column>
          <el-table-column label="净收益%" width="100" sortable prop="pnl_pct">
            <template #default="{ row }">
              <span class="num" :class="cls(row.pnl_pct)" style="font-weight:700">{{ sign(row.pnl_pct) }}%</span>
            </template>
          </el-table-column>
          <el-table-column label="持有" width="70">
            <template #default="{ row }"><span class="num">{{ row.hold_days }}d</span></template>
          </el-table-column>
          <el-table-column label="评分" width="70">
            <template #default="{ row }"><span class="num">{{ row.score?.toFixed(0) }}</span></template>
          </el-table-column>
          <el-table-column label="卖出原因" prop="sell_reason" min-width="120" show-overflow-tooltip />
          <el-table-column label="胜负" width="64">
            <template #default="{ row }">
              <el-tag size="small" :type="row.is_win ? 'danger' : 'success'" effect="dark">{{ row.is_win ? '盈' : '亏' }}</el-tag>
            </template>
          </el-table-column>
        </el-table>
      </el-card>
    </template>
  </div>
</template>

<script setup lang="ts">
import { ref, nextTick, onMounted, onUnmounted } from 'vue'
import { ElMessage } from 'element-plus'
import * as echarts from 'echarts'
import { get, post } from '@/api/client'

function verdictStyle(v: string) {
  const m: Record<string, string> = {
    '打平被动': 'background:#1c3d2e;color:#26d07c;border:1px solid #26d07c',
    '样本外证伪': 'background:#3a2330;color:#ff5c5c;border:1px solid #ff5c5c',
    '封板幻觉': 'background:#3a2330;color:#ff5c5c;border:1px solid #ff5c5c',
    '偏弱未充分验证': 'background:#3a3320;color:#f0b429;border:1px solid #f0b429',
    '未独立验证': 'background:#2a2f3a;color:#9aa7b8;border:1px solid #5f6b7c',
  }
  return m[v] || m['未独立验证']
}

const styles = ref<any[]>([])
const selected = ref<string>('')
const range = ref<[string, string]>(['2025-10-01', '2026-04-14'])
const initialCash = ref(100000)
const running = ref(false)
const errorMsg = ref('')
const result = ref<any>(null)

const equityRef = ref<HTMLElement | null>(null)
const eventRef = ref<HTMLElement | null>(null)
let equityChart: echarts.ECharts | null = null
let eventChart: echarts.ECharts | null = null

function fmt(v: number | null | undefined, d = 2) {
  if (v == null || isNaN(v as number)) return '--'
  return Number(v).toFixed(d)
}
function sign(v: number | null | undefined) {
  if (v == null || isNaN(v as number)) return '--'
  return (v >= 0 ? '+' : '') + Number(v).toFixed(2)
}
function cls(v: number | null | undefined) {
  if (v == null) return ''
  return v >= 0 ? 'up' : 'down'
}

async function loadStyles() {
  try {
    const res: any = await get('/styles/list')
    styles.value = res.styles || []
    // 默认选中唯一验证未亏的（打平被动），而非把已证伪策略当默认
    if (styles.value.length && !selected.value) {
      const ok = styles.value.find((x: any) => x.verdict === '打平被动')
      selected.value = (ok || styles.value[0]).key
    }
  } catch (e: any) {
    ElMessage.error('加载风格列表失败：' + (e.message || ''))
  }
}

async function run() {
  if (!selected.value) return
  running.value = true
  errorMsg.value = ''
  result.value = null
  try {
    const qs = new URLSearchParams({
      start_date: range.value?.[0] ?? '',
      end_date: range.value?.[1] ?? '',
      initial_cash: String(initialCash.value),
    }).toString()
    const res: any = await post(`/styles/${selected.value}/backtest?${qs}`)
    if (res?.error) {
      errorMsg.value = res.error
      return
    }
    result.value = res
    ElMessage.success('回测完成')
    nextTick(() => {
      renderEquity()
      renderEvent()
    })
  } catch (e: any) {
    errorMsg.value = '回测失败：' + (e.response?.data?.detail || e.message || '未知错误')
  } finally {
    running.value = false
  }
}

function renderEquity() {
  if (!equityRef.value || !result.value?.equity_curve?.length) return
  if (!equityChart) equityChart = echarts.init(equityRef.value, 'quant')
  const ec = result.value.equity_curve
  equityChart.setOption({
    tooltip: { trigger: 'axis' },
    grid: { left: 64, right: 20, top: 20, bottom: 30 },
    xAxis: { type: 'category', data: ec.map((d: any) => d.date), axisLabel: { fontSize: 11 } },
    yAxis: { type: 'value', scale: true, name: '净值' },
    series: [{
      type: 'line',
      data: ec.map((d: any) => d.equity),
      smooth: true,
      symbol: 'none',
      lineStyle: { width: 2, color: '#3ea6ff' },
      areaStyle: {
        color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
          { offset: 0, color: 'rgba(62,166,255,0.28)' },
          { offset: 1, color: 'rgba(62,166,255,0.02)' },
        ]),
      },
    }],
  })
}

function renderEvent() {
  if (!eventRef.value || !result.value?.event_study?.length) return
  if (!eventChart) eventChart = echarts.init(eventRef.value, 'quant')
  const es = result.value.event_study
  eventChart.setOption({
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    legend: { data: ['平均收益%', '胜率%'], top: 0 },
    grid: { left: 44, right: 44, top: 34, bottom: 28 },
    xAxis: { type: 'category', data: es.map((d: any) => 'T+' + d.horizon) },
    yAxis: [
      { type: 'value', name: '收益%', position: 'left' },
      { type: 'value', name: '胜率%', position: 'right', max: 100 },
    ],
    series: [
      {
        name: '平均收益%',
        type: 'bar',
        data: es.map((d: any) => +(d.avg_ret_pct ?? 0).toFixed(2)),
        itemStyle: {
          color: (p: any) => (p.value >= 0 ? '#ff5c5c' : '#26d07c'),
        },
        barMaxWidth: 28,
        label: { show: true, position: 'top', formatter: '{c}%', color: '#9aa7b8' },
      },
      {
        name: '胜率%',
        type: 'line',
        yAxisIndex: 1,
        data: es.map((d: any) => +((d.win_rate ?? 0) * 100).toFixed(1)),
        lineStyle: { color: '#f0b429' },
        itemStyle: { color: '#f0b429' },
        symbol: 'circle',
        symbolSize: 6,
      },
    ],
  })
}

onMounted(loadStyles)
onUnmounted(() => {
  equityChart?.dispose()
  eventChart?.dispose()
  equityChart = null
  eventChart = null
})
</script>

<style scoped>
.sb-page { padding-bottom: 40px; }
.toolbar { margin-bottom: 16px; }
.style-cards {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 12px;
}
.style-card {
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 14px 16px;
  background: var(--bg-inset);
  cursor: pointer;
  transition: all 0.18s ease;
}
.style-card:hover {
  border-color: var(--border-strong);
}
.style-card.active {
  border-color: var(--accent);
  background: rgba(62, 166, 255, 0.1);
  box-shadow: 0 0 0 1px rgba(62, 166, 255, 0.4), 0 0 18px rgba(62, 166, 255, 0.18);
}
.sc-top { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.sc-name { font-size: 15px; font-weight: 700; color: var(--text-1); }
.verdict-badge { font-size: 11px; font-weight: 700; padding: 2px 8px; border-radius: 10px; white-space: nowrap; }
.sc-desc { font-size: 12px; color: var(--text-2); margin: 6px 0 6px; line-height: 1.5; }
.sc-verdict { font-size: 11px; color: var(--gold); margin-bottom: 6px; line-height: 1.5; }
.sc-meta { font-size: 11px; color: var(--text-3); }
.param-row {
  display: flex;
  align-items: center;
  gap: 16px;
  flex-wrap: wrap;
  margin-top: 16px;
  padding-top: 16px;
  border-top: 1px solid var(--border);
}
.cash-field { display: flex; align-items: center; gap: 8px; }
.cash-lbl { font-size: 13px; color: var(--text-2); }
.hint { font-size: 12px; color: var(--text-3); margin-left: auto; }

.result-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 14px;
  flex-wrap: wrap;
  gap: 12px;
}
.rh-name { font-size: 20px; font-weight: 700; color: var(--text-1); }
.rh-desc { font-size: 13px; color: var(--text-2); margin-left: 12px; }
.rh-tags { display: flex; gap: 10px; }

.kpi-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
  gap: 12px;
  margin-bottom: 16px;
}
.kpi { padding: 14px 16px; }
.kpi-l { font-size: 12px; color: var(--text-3); margin-bottom: 8px; }
.kpi-v { font-size: 22px; font-weight: 700; color: var(--text-1); }

.callout {
  margin-bottom: 16px;
  border-color: rgba(240, 180, 41, 0.5) !important;
  background: rgba(240, 180, 41, 0.07) !important;
}
.callout-head { font-size: 15px; font-weight: 700; color: var(--gold); display: flex; align-items: center; }
.callout-body { margin-top: 10px; }
.cb-main { font-size: 22px; font-weight: 800; color: var(--text-1); }
.cb-sub { font-size: 13px; color: var(--text-2); margin-top: 6px; }
.cb-note { font-size: 12px; color: var(--text-3); margin-top: 8px; line-height: 1.6; }

.realism { margin-bottom: 16px; border-color: rgba(255, 92, 92, 0.4) !important; }
.realism-list { margin: 0; padding-left: 20px; }
.realism-list li {
  font-size: 13px;
  color: var(--text-2);
  line-height: 1.9;
}
.block-card { margin-bottom: 16px; }
.up { color: var(--up); }
.down { color: var(--down); }
.gold { color: var(--gold); }
.accent { color: var(--accent); }
</style>
