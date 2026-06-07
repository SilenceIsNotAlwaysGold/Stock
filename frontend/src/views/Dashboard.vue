<template>
  <div class="dashboard">
    <div class="date-bar">
      <span style="color: var(--text-2)">数据截止</span>
      <span class="num" style="margin-left: 8px">{{ asOf || '加载中…' }}</span>
      <span style="margin-left: 12px; color: var(--text-2)">{{ asOfWeekday }}</span>
    </div>
    <el-row :gutter="20">
      <el-col :span="6">
        <el-card shadow="hover">
          <template #header>市场情绪</template>
          <div class="stat">
            <span class="value num" :style="{ color: emotionColor }">{{ emotion.score ?? '--' }}</span>
            <span class="label">{{ emotion.status ?? '加载中' }}</span>
          </div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="hover">
          <template #header>策略数量</template>
          <div class="stat">
            <span class="value num">{{ strategies.length }}</span>
            <span class="label">已注册策略</span>
          </div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="hover">
          <template #header>推荐股票</template>
          <div class="stat">
            <span class="value num">{{ overview.total_candidates ?? recommendations.length }}</span>
            <span class="label">推荐股票</span>
          </div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="hover">
          <template #header>模拟盘</template>
          <div class="stat">
            <span class="value num" :style="{ color: (overview.total_pnl ?? account.total_pnl) >= 0 ? 'var(--up)' : 'var(--down)' }">
              {{ (overview.total_pnl ?? account.total_pnl)?.toFixed(2) ?? '--' }}
            </span>
            <span class="label">总盈亏</span>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <!-- 趋势图 -->
    <el-row :gutter="20" style="margin-top: 20px">
      <el-col :span="12">
        <el-card>
          <template #header><span>市场情绪走势 (近 30 日)</span></template>
          <div ref="emotionChartRef" style="width: 100%; height: 240px"></div>
        </el-card>
      </el-col>
      <el-col :span="12">
        <el-card>
          <template #header><span>T1 每日胜率</span></template>
          <div ref="winRateChartRef" style="width: 100%; height: 240px"></div>
        </el-card>
      </el-col>
    </el-row>

    <el-row :gutter="20" style="margin-top: 20px">
      <el-col :span="12">
        <el-card>
          <template #header>推荐 TOP5 · {{ asOf || '—' }}</template>
          <el-table :data="recommendations.slice(0, 5)" size="small" stripe>
            <el-table-column prop="ts_code" label="代码" width="100" />
            <el-table-column prop="name" label="名称" width="80" />
            <el-table-column prop="action" label="信号" width="80">
              <template #default="{ row }">
                <el-tag :type="row.action === 'BUY' ? 'success' : row.action === 'SELL' ? 'danger' : 'info'" size="small">
                  {{ row.action }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="score" label="评分" width="80" />
            <el-table-column prop="buy_count" label="买入策略数" />
          </el-table>
        </el-card>
      </el-col>
      <el-col :span="12">
        <el-card>
          <template #header>策略健康度</template>
          <el-table :data="strategies" size="small" stripe>
            <el-table-column prop="name" label="策略" />
            <el-table-column prop="category" label="类别" width="80" />
            <el-table-column prop="score" label="健康度" width="80" />
            <el-table-column prop="grade" label="等级" width="100">
              <template #default="{ row }">
                <el-tag :type="gradeType(row.grade)" size="small">{{ row.grade }}</el-tag>
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-col>
    </el-row>

    <el-card style="margin-top: 16px">
      <template #header><span>T1 候选 TOP3 · {{ candDate || '—' }}</span></template>
      <el-table :data="topCandidates" size="small" stripe empty-text="该日无候选">
        <el-table-column prop="ts_code" label="代码" width="100" />
        <el-table-column prop="stock_name" label="名称" width="90" />
        <el-table-column prop="score" label="评分" width="80">
          <template #default="{ row }">
            <span class="num" :style="{ fontWeight: 700, color: row.score >= 50 ? 'var(--down)' : 'var(--gold)' }">
              {{ row.score?.toFixed(1) }}
            </span>
          </template>
        </el-table-column>
        <el-table-column prop="status" label="状态" width="80">
          <template #default="{ row }">
            <el-tag :type="row.status === 'bought' ? 'success' : 'info'" size="small">
              {{ row.status === 'bought' ? '已买' : '待选' }}
            </el-tag>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-card style="margin-top: 16px">
      <template #header><span>最近交易</span></template>
      <el-table :data="recentTrades" size="small" stripe empty-text="暂无交易记录">
        <el-table-column prop="stock_name" label="名称" width="90" />
        <el-table-column prop="sell_date" label="卖出日" width="110" />
        <el-table-column prop="pnl_pct" label="盈亏%" width="90">
          <template #default="{ row }">
            <span :class="row.pnl_pct >= 0 ? 'up' : 'down'" style="font-weight: 600">
              {{ row.pnl_pct >= 0 ? '+' : '' }}{{ row.pnl_pct?.toFixed(2) }}%
            </span>
          </template>
        </el-table-column>
        <el-table-column prop="is_win" label="胜负" width="60">
          <template #default="{ row }">
            <el-tag :type="row.is_win ? 'success' : 'danger'" size="small">{{ row.is_win ? '盈' : '亏' }}</el-tag>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, computed, nextTick } from 'vue'
import * as echarts from 'echarts'
import { emotionApi, recommendApi, strategyApi, paperApi, t1Api } from '@/api'
import { get } from '@/api/client'

const emotion = ref<any>({})
const recommendations = ref<any[]>([])
const strategies = ref<any[]>([])
const account = ref<any>({})
const overview = ref<any>({})
const topCandidates = ref<any[]>([])
const recentTrades = ref<any[]>([])
const emotionChartRef = ref<HTMLElement | null>(null)
const winRateChartRef = ref<HTMLElement | null>(null)
const emotionHistory = ref<any[]>([])
const dailyWinRates = ref<any[]>([])

const asOf = ref('')          // 真实数据截止日（最新日线交易日）
const candDate = ref('')      // T1 候选所属扫描日
const WD = ['周日', '周一', '周二', '周三', '周四', '周五', '周六']
const asOfWeekday = computed(() => {
  if (!asOf.value) return ''
  const d = new Date(asOf.value)
  return isNaN(d.getTime()) ? '' : WD[d.getDay()]
})

const emotionColor = computed(() => {
  const s = emotion.value.score ?? 50
  if (s >= 65) return 'var(--down)'
  if (s >= 45) return 'var(--gold)'
  return 'var(--up)'
})

function gradeType(grade: string) {
  if (grade === 'Core') return 'success'
  if (grade === 'Plus') return ''
  if (grade === 'Experimental') return 'warning'
  return 'danger'
}

async function loadDashboard() {
  try {
    const r: any = await t1Api.dashboard()
    if (r.overview) {
      overview.value = r.overview
    }
    topCandidates.value = r.top_candidates || []
    recentTrades.value = r.recent_trades || []
    dailyWinRates.value = r.daily_win_rates || []
    if (r.as_of) asOf.value = r.as_of
    if (r.candidates_date) candDate.value = r.candidates_date
  } catch (e) {
    console.error('加载仪表盘数据失败:', e)
  }
}

async function loadEmotionHistory() {
  try {
    emotionHistory.value = await get('/emotion/history', { days: 30 })
  } catch { /* 忽略 */ }
}

function renderEmotionChart() {
  if (!emotionChartRef.value) return
  const data = emotionHistory.value
  // 即使为空也显示空图，避免首次为空时不创建实例
  const dates = data.map((d: any) => d.date)
  const scores = data.map((d: any) => d.score)
  const chart = echarts.init(emotionChartRef.value, 'quant')
  chart.setOption({
    tooltip: { trigger: 'axis' },
    grid: { left: 40, right: 16, top: 24, bottom: 30 },
    xAxis: { type: 'category', data: dates, axisLabel: { fontSize: 11 } },
    yAxis: { type: 'value', min: 0, max: 100, splitLine: { lineStyle: { type: 'dashed' } } },
    series: [{
      type: 'line', data: scores, smooth: true, symbol: 'circle', symbolSize: 6,
      lineStyle: { width: 2, color: '#3ea6ff' },
      itemStyle: { color: '#3ea6ff' },
      areaStyle: { color: 'rgba(62,166,255,0.15)' },
      markLine: { silent: true, lineStyle: { color: '#f0b429', type: 'dashed' }, data: [{ yAxis: 50 }] },
    }],
  })
  if (!data.length) {
    chart.setOption({ title: { text: '暂无历史数据', left: 'center', top: 'middle', textStyle: { color: '#909399', fontSize: 13 } } })
  }
}

function renderWinRateChart() {
  if (!winRateChartRef.value) return
  const data = dailyWinRates.value
  const dates = data.map((d: any) => d.date)
  const rates = data.map((d: any) => (d.win_rate ?? 0) * 100)
  const counts = data.map((d: any) => d.trades ?? d.total_trades ?? 0)
  const chart = echarts.init(winRateChartRef.value, 'quant')
  chart.setOption({
    tooltip: { trigger: 'axis' },
    legend: { data: ['胜率%', '交易笔数'], right: 0 },
    grid: { left: 40, right: 50, top: 30, bottom: 30 },
    xAxis: { type: 'category', data: dates, axisLabel: { fontSize: 11 } },
    yAxis: [
      { type: 'value', max: 100, name: '胜率%', position: 'left' },
      { type: 'value', name: '笔数', position: 'right' },
    ],
    series: [
      { name: '胜率%', type: 'line', data: rates, smooth: true, lineStyle: { color: '#3ea6ff' }, itemStyle: { color: '#3ea6ff' } },
      { name: '交易笔数', type: 'bar', yAxisIndex: 1, data: counts, itemStyle: { color: 'rgba(240,180,41,0.45)' } },
    ],
  })
  if (!data.length) {
    chart.setOption({ title: { text: '暂无交易记录', left: 'center', top: 'middle', textStyle: { color: '#909399', fontSize: 13 } } })
  }
}

onMounted(async () => {
  try { emotion.value = await emotionApi.today() } catch (e) { console.error('加载市场情绪失败:', e) }
  try {
    const res: any = await recommendApi.today(5)
    recommendations.value = res.recommendations ?? []
    if (!asOf.value && res.as_of) asOf.value = res.as_of
  } catch (e) { console.error('加载推荐失败:', e) }
  try { strategies.value = await strategyApi.healthList() } catch (e) { console.error('加载策略失败:', e) }
  try { account.value = await paperApi.account() } catch (e) { console.error('加载账户失败:', e) }
  await Promise.all([loadDashboard(), loadEmotionHistory()])
  nextTick(() => { renderEmotionChart(); renderWinRateChart() })
})
</script>

<style scoped>
.dashboard { padding-bottom: 32px; }
.stat { text-align: center; padding: 12px 0; }
.stat .value {
  font-size: 32px;
  font-weight: 700;
  display: block;
  color: var(--text-1);
  letter-spacing: 0.5px;
}
.stat .label { color: var(--text-2); font-size: 13px; margin-top: 4px; display: block; }
.date-bar {
  font-size: 18px;
  font-weight: 600;
  margin-bottom: 16px;
  color: var(--text-1);
}
.up { color: var(--up); }
.down { color: var(--down); }
</style>
