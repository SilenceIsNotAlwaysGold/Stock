import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import 'element-plus/theme-chalk/dark/css-vars.css'
import './styles/theme.css'
import * as ElementPlusIconsVue from '@element-plus/icons-vue'
import * as echarts from 'echarts'

import App from './App.vue'
import router from './router'

// 全局 echarts 暗色主题：trading-terminal 风格
echarts.registerTheme('quant', {
  backgroundColor: 'transparent',
  color: ['#3ea6ff', '#2bd4c4', '#f0b429', '#ff5c5c', '#26d07c', '#a371f7'],
  textStyle: { color: '#9aa7b8' },
  title: {
    textStyle: { color: '#e6edf3' },
    subtextStyle: { color: '#9aa7b8' },
  },
  legend: {
    textStyle: { color: '#9aa7b8' },
  },
  categoryAxis: {
    axisLine: { lineStyle: { color: '#232a36' } },
    axisTick: { lineStyle: { color: '#232a36' } },
    axisLabel: { color: '#9aa7b8' },
    splitLine: { show: false, lineStyle: { color: '#232a36', type: 'dashed' } },
  },
  valueAxis: {
    axisLine: { show: false, lineStyle: { color: '#232a36' } },
    axisTick: { lineStyle: { color: '#232a36' } },
    axisLabel: { color: '#9aa7b8' },
    splitLine: { lineStyle: { color: '#232a36', type: 'dashed' } },
  },
  timeAxis: {
    axisLine: { lineStyle: { color: '#232a36' } },
    axisLabel: { color: '#9aa7b8' },
    splitLine: { lineStyle: { color: '#232a36', type: 'dashed' } },
  },
  logAxis: {
    axisLine: { lineStyle: { color: '#232a36' } },
    axisLabel: { color: '#9aa7b8' },
    splitLine: { lineStyle: { color: '#232a36', type: 'dashed' } },
  },
  tooltip: {
    backgroundColor: '#161b24',
    borderColor: '#232a36',
    textStyle: { color: '#e6edf3' },
    axisPointer: {
      lineStyle: { color: '#2f3947' },
      crossStyle: { color: '#2f3947' },
    },
  },
  dataZoom: {
    textStyle: { color: '#9aa7b8' },
    borderColor: '#232a36',
  },
})

const app = createApp(App)

app.use(createPinia())
app.use(router)
app.use(ElementPlus)

// 注册所有图标
for (const [key, component] of Object.entries(ElementPlusIconsVue)) {
  app.component(key, component)
}

app.mount('#app')
