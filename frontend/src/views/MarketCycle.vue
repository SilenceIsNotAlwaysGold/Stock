<template>
  <div class="cycle-page">
    <!-- 工具栏 -->
    <el-card class="toolbar">
      <div class="toolbar-row">
        <el-date-picker
          v-model="range"
          type="daterange"
          value-format="YYYY-MM-DD"
          range-separator="→"
          start-placeholder="开始日期"
          end-placeholder="结束日期"
          style="width: 320px"
        />
        <el-button type="primary" :loading="loading" @click="load">
          <el-icon><Refresh /></el-icon>&nbsp;{{ loading ? '计算中...' : '获取情绪周期' }}
        </el-button>
        <span class="hint">全市场截面计算，无未来函数 · A 股短线最大 edge：冰点空仓、高潮放大</span>
      </div>
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
      v-if="!loading && !errorMsg && !series.length"
      description="选择日期范围后点击「获取情绪周期」"
      style="margin-top: 60px"
    />

    <template v-if="series.length">
      <!-- 当前情绪 Hero -->
      <el-card v-if="latest" class="hero glass">
        <div class="hero-grid">
          <div class="hero-phase">
            <div class="phase-badge" :style="{ background: phaseBg(latest.phase), color: phaseColor(latest.phase) }">
              {{ latest.phase }}
            </div>
            <div class="hero-date num">{{ latest.date }}</div>
          </div>
          <div class="hero-score">
            <el-progress
              type="dashboard"
              :percentage="Math.round(latest.score)"
              :color="phaseColor(latest.phase)"
              :width="130"
              :stroke-width="10"
            >
              <template #default>
                <div class="score-inner">
                  <div class="score-val num">{{ latest.score?.toFixed(0) }}</div>
                  <div class="score-lbl">情绪分</div>
                </div>
              </template>
            </el-progress>
          </div>
          <div class="hero-stats">
            <div class="hs"><span class="hs-l">涨停</span><span class="hs-v up num">{{ latest.limit_up }}</span></div>
            <div class="hs"><span class="hs-l">跌停</span><span class="hs-v down num">{{ latest.limit_down }}</span></div>
            <div class="hs"><span class="hs-l">炸板率</span><span class="hs-v num">{{ pct(latest.broken_rate) }}</span></div>
            <div class="hs"><span class="hs-l">最高连板</span><span class="hs-v gold num">{{ latest.max_consecutive }}</span></div>
            <div class="hs"><span class="hs-l">晋级率</span><span class="hs-v num">{{ pct(latest.advance_rate) }}</span></div>
            <div class="hs"><span class="hs-l">钱效</span><span class="hs-v num">{{ pct(latest.money_effect) }}</span></div>
            <div class="hs"><span class="hs-l">仓位 gate</span><span class="hs-v accent num">{{ (latest.gate * 100).toFixed(0) }}%</span></div>
          </div>
        </div>
        <div v-if="latest.note" class="hero-note">{{ latest.note }}</div>
      </el-card>

      <!-- 走势图 -->
      <el-card class="chart-card">
        <template #header><span>情绪曲线 + 涨停 / 跌停</span></template>
        <div ref="chartRef" style="width: 100%; height: 380px"></div>
      </el-card>

      <!-- 序列表格 -->
      <el-card class="table-card">
        <template #header><span>情绪周期明细 ({{ count }} 个交易日)</span></template>
        <el-table :data="reversedSeries" size="small" stripe height="460">
          <el-table-column label="日期" prop="date" width="110" />
          <el-table-column label="相位" width="90">
            <template #default="{ row }">
              <el-tag size="small" :style="tagStyle(row.phase)" effect="plain">{{ row.phase }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="情绪分" width="90" sortable prop="score">
            <template #default="{ row }">
              <span class="num" :style="{ fontWeight: 700, color: phaseColor(row.phase) }">{{ row.score?.toFixed(1) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="涨停" width="80" sortable prop="limit_up">
            <template #default="{ row }"><span class="up num">{{ row.limit_up }}</span></template>
          </el-table-column>
          <el-table-column label="跌停" width="80" sortable prop="limit_down">
            <template #default="{ row }"><span class="down num">{{ row.limit_down }}</span></template>
          </el-table-column>
          <el-table-column label="炸板率" width="90">
            <template #default="{ row }"><span class="num">{{ pct(row.broken_rate) }}</span></template>
          </el-table-column>
          <el-table-column label="最高连板" width="100" sortable prop="max_consecutive">
            <template #default="{ row }"><span class="gold num">{{ row.max_consecutive }}</span></template>
          </el-table-column>
          <el-table-column label="晋级率" width="90">
            <template #default="{ row }"><span class="num">{{ pct(row.advance_rate) }}</span></template>
          </el-table-column>
          <el-table-column label="钱效" width="90">
            <template #default="{ row }"><span class="num">{{ pct(row.money_effect) }}</span></template>
          </el-table-column>
          <el-table-column label="仓位 gate" width="100">
            <template #default="{ row }"><span class="accent num">{{ (row.gate * 100).toFixed(0) }}%</span></template>
          </el-table-column>
          <el-table-column label="说明" prop="note" min-width="160" show-overflow-tooltip />
        </el-table>
      </el-card>
    </template>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, nextTick, onUnmounted } from 'vue'
import { ElMessage } from 'element-plus'
import * as echarts from 'echarts'
import { get } from '@/api/client'

const loading = ref(false)
const errorMsg = ref('')
const range = ref<[string, string]>(['2026-02-11', '2026-04-24'])
const series = ref<any[]>([])
const latest = ref<any>(null)
const count = ref(0)
const chartRef = ref<HTMLElement | null>(null)
let chart: echarts.ECharts | null = null

const reversedSeries = computed(() => [...series.value].slice().reverse())

const PHASE_COLOR: Record<string, string> = {
  '高潮': '#ff5c5c',
  '发酵': '#f0b429',
  '修复': '#3ea6ff',
  '退潮': '#9aa7b8',
  '冰点': '#26d07c',
}
function phaseColor(p: string) { return PHASE_COLOR[p] || '#9aa7b8' }
function phaseBg(p: string) {
  const c = phaseColor(p)
  return c + '22'
}
function tagStyle(p: string) {
  const c = phaseColor(p)
  return { color: c, borderColor: c, background: c + '1f' }
}
function pct(v: number | null | undefined) {
  if (v == null) return '--'
  return (v * 100).toFixed(1) + '%'
}

async function load() {
  loading.value = true
  errorMsg.value = ''
  try {
    const res: any = await get('/emotion/cycle', {
      start_date: range.value?.[0],
      end_date: range.value?.[1],
    })
    if (res?.error) {
      errorMsg.value = res.error
      series.value = []
      latest.value = null
      count.value = 0
      return
    }
    series.value = res.series || []
    latest.value = res.latest || null
    count.value = res.count ?? series.value.length
    if (!series.value.length) {
      ElMessage.warning('该区间无情绪数据')
    } else {
      ElMessage.success(`已加载 ${count.value} 个交易日`)
      nextTick(renderChart)
    }
  } catch (e: any) {
    errorMsg.value = '获取失败：' + (e.response?.data?.detail || e.message || '未知错误')
  } finally {
    loading.value = false
  }
}

function renderChart() {
  if (!chartRef.value) return
  if (!chart) chart = echarts.init(chartRef.value, 'quant')
  const dates = series.value.map((d) => d.date)
  const scores = series.value.map((d) => d.score)
  const ups = series.value.map((d) => d.limit_up)
  const downs = series.value.map((d) => -Math.abs(d.limit_down || 0))

  chart.setOption({
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'cross' },
      formatter: (ps: any[]) => {
        const i = ps[0].dataIndex
        const s = series.value[i]
        return `${s.date}<br/>相位：<b style="color:${phaseColor(s.phase)}">${s.phase}</b><br/>` +
          `情绪分：${s.score?.toFixed(1)}<br/>涨停：${s.limit_up}　跌停：${s.limit_down}<br/>` +
          `炸板率：${pct(s.broken_rate)}　连板：${s.max_consecutive}<br/>仓位 gate：${(s.gate * 100).toFixed(0)}%`
      },
    },
    legend: { data: ['情绪分', '涨停数', '跌停数'], top: 0 },
    grid: { left: 48, right: 56, top: 36, bottom: 30 },
    xAxis: { type: 'category', data: dates, axisLabel: { fontSize: 11 } },
    yAxis: [
      { type: 'value', name: '情绪分', min: 0, max: 100, position: 'left' },
      { type: 'value', name: '涨/跌停', position: 'right' },
    ],
    series: [
      {
        name: '情绪分',
        type: 'line',
        data: scores,
        smooth: true,
        symbol: 'circle',
        symbolSize: 5,
        lineStyle: { width: 2, color: '#3ea6ff' },
        itemStyle: { color: '#3ea6ff' },
        areaStyle: { color: 'rgba(62,166,255,0.14)' },
        markLine: {
          silent: true,
          lineStyle: { color: '#f0b429', type: 'dashed' },
          data: [{ yAxis: 50 }],
        },
      },
      { name: '涨停数', type: 'bar', yAxisIndex: 1, data: ups, itemStyle: { color: 'rgba(255,92,92,0.6)' }, barMaxWidth: 14 },
      { name: '跌停数', type: 'bar', yAxisIndex: 1, data: downs, itemStyle: { color: 'rgba(38,208,124,0.55)' }, barMaxWidth: 14 },
    ],
  })
}

onUnmounted(() => {
  chart?.dispose()
  chart = null
})
</script>

<style scoped>
.cycle-page { padding-bottom: 40px; }
.toolbar { margin-bottom: 16px; }
.toolbar-row { display: flex; align-items: center; gap: 16px; flex-wrap: wrap; }
.hint { font-size: 12px; color: var(--text-3); margin-left: auto; }
.hero { margin-bottom: 16px; }
.hero-grid {
  display: flex;
  align-items: center;
  gap: 36px;
  flex-wrap: wrap;
}
.hero-phase { text-align: center; }
.phase-badge {
  display: inline-block;
  padding: 8px 22px;
  border-radius: 999px;
  font-size: 20px;
  font-weight: 800;
  letter-spacing: 2px;
}
.hero-date { margin-top: 10px; font-size: 13px; color: var(--text-2); }
.score-inner { text-align: center; }
.score-val { font-size: 28px; font-weight: 800; color: var(--text-1); }
.score-lbl { font-size: 12px; color: var(--text-3); margin-top: 2px; }
.hero-stats {
  display: grid;
  grid-template-columns: repeat(4, auto);
  gap: 14px 32px;
  flex: 1;
}
.hs { display: flex; flex-direction: column; gap: 4px; }
.hs-l { font-size: 12px; color: var(--text-3); }
.hs-v { font-size: 20px; font-weight: 700; color: var(--text-1); }
.hero-note {
  margin-top: 18px;
  padding-top: 14px;
  border-top: 1px solid var(--border);
  font-size: 13px;
  color: var(--text-2);
  line-height: 1.7;
}
.chart-card { margin-bottom: 16px; }
.up { color: var(--up); }
.down { color: var(--down); }
.gold { color: var(--gold); }
.accent { color: var(--accent); }
</style>
