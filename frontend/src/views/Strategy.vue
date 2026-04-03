<template>
  <div>
    <el-card>
      <template #header>策略管理</template>
      <el-table :data="strategies" stripe>
        <el-table-column prop="name" label="策略名称" width="160" />
        <el-table-column prop="description" label="描述" />
        <el-table-column prop="category" label="类别" width="100" />
        <el-table-column prop="score" label="健康度" width="80" />
        <el-table-column prop="grade" label="等级" width="120">
          <template #default="{ row }">
            <el-tag :type="gradeType(row.grade)" size="small">{{ row.grade }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="win_rate" label="胜率%" width="80" />
        <el-table-column prop="total_signals" label="信号数" width="80" />
      </el-table>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { strategyApi } from '@/api'

const strategies = ref<any[]>([])

function gradeType(grade: string) {
  if (grade === 'Core') return 'success'
  if (grade === 'Plus') return ''
  if (grade === 'Experimental') return 'warning'
  return 'danger'
}

onMounted(async () => {
  try { strategies.value = await strategyApi.healthList() as any } catch {}
})
</script>
