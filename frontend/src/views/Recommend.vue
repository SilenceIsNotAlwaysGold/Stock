<template>
  <div>
    <el-card>
      <template #header>
        每日推荐
        <span style="float: right; font-size: 14px; color: #909399">{{ date }}</span>
      </template>
      <el-button type="primary" @click="loadRecommendations" :loading="loading" style="margin-bottom: 16px">
        刷新推荐
      </el-button>
      <el-table :data="recommendations" stripe>
        <el-table-column prop="ts_code" label="代码" width="120" />
        <el-table-column prop="name" label="名称" width="100" />
        <el-table-column prop="action" label="信号" width="80">
          <template #default="{ row }">
            <el-tag :type="row.action === 'BUY' ? 'success' : row.action === 'SELL' ? 'danger' : 'info'" size="small">
              {{ row.action }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="score" label="综合评分" width="100" />
        <el-table-column prop="buy_count" label="买入策略" width="100" />
        <el-table-column prop="sell_count" label="卖出策略" width="100" />
        <el-table-column prop="resonance" label="共振" width="80">
          <template #default="{ row }">
            <el-tag v-if="row.resonance" type="warning" size="small">共振</el-tag>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { recommendApi } from '@/api'

const recommendations = ref<any[]>([])
const loading = ref(false)
const date = ref('')

async function loadRecommendations() {
  loading.value = true
  try {
    const res: any = await recommendApi.today(20)
    recommendations.value = res.recommendations ?? []
    date.value = res.date ?? ''
  } finally {
    loading.value = false
  }
}

onMounted(loadRecommendations)
</script>
