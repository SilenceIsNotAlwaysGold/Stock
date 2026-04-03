<template>
  <div>
    <el-card>
      <template #header>策略回测</template>
      <el-form inline>
        <el-form-item label="股票代码">
          <el-input v-model="form.stock_code" placeholder="000001.SZ" style="width: 160px" />
        </el-form-item>
        <el-form-item label="策略">
          <el-select v-model="form.strategy_name" placeholder="全部策略" clearable style="width: 160px">
            <el-option v-for="s in strategies" :key="s.name" :label="s.description" :value="s.name" />
          </el-select>
        </el-form-item>
        <el-form-item label="起始日期">
          <el-input v-model="form.start_date" placeholder="2024-01-01" style="width: 140px" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="runBacktest" :loading="loading">运行回测</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <el-card v-if="results.length" style="margin-top: 20px">
      <template #header>回测结果</template>
      <el-table :data="results" stripe>
        <el-table-column prop="strategy" label="策略" width="140" />
        <el-table-column prop="total_return" label="总收益%" width="100">
          <template #default="{ row }">
            <span :style="{ color: row.total_return >= 0 ? '#67c23a' : '#f56c6c' }">
              {{ row.total_return }}%
            </span>
          </template>
        </el-table-column>
        <el-table-column prop="annual_return" label="年化%" width="100" />
        <el-table-column prop="max_drawdown" label="最大回撤%" width="100" />
        <el-table-column prop="win_rate" label="胜率%" width="80" />
        <el-table-column prop="total_trades" label="交易次数" width="100" />
        <el-table-column prop="final_equity" label="最终资产" />
      </el-table>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { backtestApi } from '@/api'

const form = ref({ stock_code: '000001.SZ', strategy_name: '', start_date: '2024-01-01' })
const strategies = ref<any[]>([])
const results = ref<any[]>([])
const loading = ref(false)

async function runBacktest() {
  loading.value = true
  try {
    const res: any = await backtestApi.run(form.value)
    results.value = res.results ?? []
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  try {
    strategies.value = await backtestApi.strategies() as any
  } catch {}
})
</script>
