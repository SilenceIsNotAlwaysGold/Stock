<template>
  <div ref="chartRef" :style="{ width: '100%', height: height + 'px' }"></div>
</template>

<script setup lang="ts">
import { ref, onMounted, watch, onUnmounted } from 'vue'
import * as echarts from 'echarts'

const props = defineProps<{
  data: Array<{
    trade_date: string
    open: number
    high: number
    low: number
    close: number
    volume: number
  }>
  height?: number
}>()

const height = props.height ?? 500
const chartRef = ref<HTMLElement>()
let chart: echarts.ECharts | null = null

function renderChart() {
  if (!chartRef.value || !props.data?.length) return

  if (!chart) {
    chart = echarts.init(chartRef.value, 'quant')
  }

  const dates = props.data.map((d) => d.trade_date)
  const ohlc = props.data.map((d) => [d.open, d.close, d.low, d.high])
  const volumes = props.data.map((d) => d.volume)

  // MA 计算
  const ma = (n: number) =>
    props.data.map((_, i) => {
      if (i < n - 1) return '-'
      const sum = props.data.slice(i - n + 1, i + 1).reduce((s, d) => s + d.close, 0)
      return (sum / n).toFixed(2)
    })

  const option: echarts.EChartsOption = {
    tooltip: { trigger: 'axis', axisPointer: { type: 'cross' } },
    legend: { data: ['K线', 'MA5', 'MA10', 'MA20'] },
    grid: [
      { left: '8%', right: '3%', top: '10%', height: '55%' },
      { left: '8%', right: '3%', top: '72%', height: '18%' },
    ],
    xAxis: [
      { type: 'category', data: dates, gridIndex: 0, boundaryGap: true },
      { type: 'category', data: dates, gridIndex: 1, boundaryGap: true },
    ],
    yAxis: [
      { scale: true, gridIndex: 0 },
      { scale: true, gridIndex: 1, splitNumber: 2 },
    ],
    dataZoom: [
      { type: 'inside', xAxisIndex: [0, 1], start: 60, end: 100 },
      { type: 'slider', xAxisIndex: [0, 1], start: 60, end: 100, top: '93%' },
    ],
    series: [
      {
        name: 'K线',
        type: 'candlestick',
        data: ohlc,
        xAxisIndex: 0,
        yAxisIndex: 0,
        itemStyle: {
          color: '#ff5c5c',
          color0: '#26d07c',
          borderColor: '#ff5c5c',
          borderColor0: '#26d07c',
        },
      },
      { name: 'MA5', type: 'line', data: ma(5), smooth: true, lineStyle: { width: 1 }, symbol: 'none' },
      { name: 'MA10', type: 'line', data: ma(10), smooth: true, lineStyle: { width: 1 }, symbol: 'none' },
      { name: 'MA20', type: 'line', data: ma(20), smooth: true, lineStyle: { width: 1 }, symbol: 'none' },
      {
        name: '成交量',
        type: 'bar',
        data: volumes,
        xAxisIndex: 1,
        yAxisIndex: 1,
        itemStyle: {
          color: (params: any) => {
            const d = props.data[params.dataIndex]
            return d.close >= d.open ? '#ff5c5c' : '#26d07c'
          },
        },
      },
    ],
  }

  chart.setOption(option)
}

onMounted(() => {
  renderChart()
  window.addEventListener('resize', () => chart?.resize())
})

watch(() => props.data, renderChart, { deep: true })

onUnmounted(() => {
  chart?.dispose()
  chart = null
})
</script>
