<template>
  <div ref="chartRef" :style="{ width: '100%', height: height + 'px' }"></div>
</template>

<script setup lang="ts">
import { ref, onMounted, watch, onUnmounted } from 'vue'
import * as echarts from 'echarts'

const props = defineProps<{
  data: Array<{
    criterion: string
    win_rate: number
    total_trades: number
    avg_pnl_pct: number
  }>
  height?: number
}>()

const height = props.height || 350
const chartRef = ref<HTMLElement>()
let chart: echarts.ECharts | null = null

const CRITERION_LABELS: Record<string, string> = {
  limit_reopen: '涨停回封',
  tail_surge: '尾盘拉升',
  sector_leader: '板块龙头',
}

function renderChart() {
  if (!chartRef.value || !props.data.length) return
  if (!chart) {
    chart = echarts.init(chartRef.value, 'quant')
  }

  const names = props.data.map(d => CRITERION_LABELS[d.criterion] || d.criterion)
  const winRates = props.data.map(d => +(d.win_rate * 100).toFixed(1))
  const avgPnl = props.data.map(d => +d.avg_pnl_pct.toFixed(2))
  const totals = props.data.map(d => d.total_trades)

  chart.setOption({
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    legend: { data: ['胜率(%)', '平均盈亏(%)', '交易次数'] },
    grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
    xAxis: { type: 'category', data: names },
    yAxis: [
      { type: 'value', name: '百分比(%)', position: 'left' },
      { type: 'value', name: '次数', position: 'right' },
    ],
    series: [
      {
        name: '胜率(%)',
        type: 'bar',
        data: winRates,
        itemStyle: { color: '#67C23A' },
        label: { show: true, position: 'top', formatter: '{c}%' },
      },
      {
        name: '平均盈亏(%)',
        type: 'bar',
        data: avgPnl,
        itemStyle: {
          color: (params: any) => (params.value >= 0 ? '#E6A23C' : '#F56C6C'),
        },
        label: { show: true, position: 'top', formatter: '{c}%' },
      },
      {
        name: '交易次数',
        type: 'line',
        yAxisIndex: 1,
        data: totals,
        itemStyle: { color: '#409EFF' },
        label: { show: true, position: 'top' },
      },
    ],
  })
}

onMounted(() => {
  renderChart()
  window.addEventListener('resize', () => chart?.resize())
})

watch(() => props.data, renderChart, { deep: true })

onUnmounted(() => {
  chart?.dispose()
  window.removeEventListener('resize', () => chart?.resize())
})
</script>
