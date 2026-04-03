<template>
  <div class="analysis">
    <el-card>
      <template #header>智能分析 - 多 Agent 协作</template>
      <el-form inline>
        <el-form-item label="股票代码">
          <el-input v-model="stockCode" placeholder="如 000001.SZ" style="width: 200px" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="startAnalysis" :loading="analyzing">
            开始分析
          </el-button>
        </el-form-item>
      </el-form>

      <div v-if="analyzing" style="margin-top: 20px">
        <el-progress :percentage="progress" :status="progressStatus" />
        <p style="color: #909399; margin-top: 8px">{{ currentNode }}</p>
      </div>
    </el-card>

    <el-card v-if="report" style="margin-top: 20px">
      <template #header>
        分析报告 - {{ report.stock_code }}
        <el-tag :type="report.decision?.action === 'BUY' ? 'success' : report.decision?.action === 'SELL' ? 'danger' : 'info'" style="margin-left: 10px">
          {{ report.decision?.action }} ({{ (report.decision?.confidence * 100).toFixed(0) }}%)
        </el-tag>
      </template>

      <el-tabs>
        <el-tab-pane label="K线图">
          <KLineChart :stock-code="stockCode" />
        </el-tab-pane>
        <el-tab-pane label="技术面">
          <pre class="report-text">{{ report.analysts?.market }}</pre>
        </el-tab-pane>
        <el-tab-pane label="基本面">
          <pre class="report-text">{{ report.analysts?.fundamental }}</pre>
        </el-tab-pane>
        <el-tab-pane label="新闻面">
          <pre class="report-text">{{ report.analysts?.news }}</pre>
        </el-tab-pane>
        <el-tab-pane label="情绪面">
          <pre class="report-text">{{ report.analysts?.sentiment }}</pre>
        </el-tab-pane>
        <el-tab-pane label="多空辩论">
          <h4>多头论点</h4>
          <pre class="report-text">{{ report.debate?.bull }}</pre>
          <h4>空头论点</h4>
          <pre class="report-text">{{ report.debate?.bear }}</pre>
          <h4>研究结论</h4>
          <pre class="report-text">{{ report.debate?.conclusion }}</pre>
        </el-tab-pane>
        <el-tab-pane label="风控评估">
          <pre class="report-text">{{ JSON.stringify(report.risk, null, 2) }}</pre>
        </el-tab-pane>
      </el-tabs>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { analysisApi } from '@/api'
import KLineChart from '@/components/KLineChart.vue'

const stockCode = ref('000001.SZ')
const analyzing = ref(false)
const progress = ref(0)
const currentNode = ref('')
const report = ref<any>(null)

const progressStatus = computed(() => progress.value >= 100 ? 'success' : '')

async function startAnalysis() {
  analyzing.value = true
  progress.value = 0
  report.value = null

  try {
    const res: any = await analysisApi.analyze(stockCode.value)
    const taskId = res.task_id

    // 轮询进度
    const poll = setInterval(async () => {
      try {
        const task: any = await analysisApi.report(taskId)
        if (task.status === 'completed' || task.analysts) {
          clearInterval(poll)
          progress.value = 100
          report.value = task
          analyzing.value = false
        } else if (task.status === 'failed') {
          clearInterval(poll)
          analyzing.value = false
        } else {
          progress.value = Math.min(progress.value + 5, 95)
          currentNode.value = task.current_node || '分析中...'
        }
      } catch {
        progress.value = Math.min(progress.value + 3, 95)
      }
    }, 2000)
  } catch {
    analyzing.value = false
  }
}
</script>

<style scoped>
.report-text { white-space: pre-wrap; font-size: 13px; line-height: 1.6; background: #f5f7fa; padding: 12px; border-radius: 4px; max-height: 400px; overflow-y: auto; }
</style>
