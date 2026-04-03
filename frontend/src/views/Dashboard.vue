<template>
  <div class="dashboard">
    <div class="date-bar">
      <span>{{ today }}</span>
      <span style="margin-left: 12px; color: #909399">{{ weekday }}</span>
    </div>
    <el-row :gutter="20">
      <el-col :span="6">
        <el-card shadow="hover">
          <template #header>市场情绪</template>
          <div class="stat">
            <span class="value" :style="{ color: emotionColor }">{{ emotion.score ?? '--' }}</span>
            <span class="label">{{ emotion.status ?? '加载中' }}</span>
          </div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="hover">
          <template #header>策略数量</template>
          <div class="stat">
            <span class="value">{{ strategies.length }}</span>
            <span class="label">已注册策略</span>
          </div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="hover">
          <template #header>今日推荐</template>
          <div class="stat">
            <span class="value">{{ recommendations.length }}</span>
            <span class="label">推荐股票</span>
          </div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="hover">
          <template #header>模拟盘</template>
          <div class="stat">
            <span class="value" :style="{ color: account.total_pnl >= 0 ? '#67c23a' : '#f56c6c' }">
              {{ account.total_pnl?.toFixed(2) ?? '--' }}
            </span>
            <span class="label">总盈亏</span>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <el-row :gutter="20" style="margin-top: 20px">
      <el-col :span="12">
        <el-card>
          <template #header>今日推荐 TOP5</template>
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
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { emotionApi, recommendApi, strategyApi, paperApi } from '@/api'

const emotion = ref<any>({})
const recommendations = ref<any[]>([])
const strategies = ref<any[]>([])
const account = ref<any>({})

const now = new Date()
const today = `${now.getFullYear()}年${now.getMonth() + 1}月${now.getDate()}日`
const weekday = ['周日', '周一', '周二', '周三', '周四', '周五', '周六'][now.getDay()]

const emotionColor = computed(() => {
  const s = emotion.value.score ?? 50
  if (s >= 65) return '#67c23a'
  if (s >= 45) return '#e6a23c'
  return '#f56c6c'
})

function gradeType(grade: string) {
  if (grade === 'Core') return 'success'
  if (grade === 'Plus') return ''
  if (grade === 'Experimental') return 'warning'
  return 'danger'
}

onMounted(async () => {
  try { emotion.value = await emotionApi.today() } catch {}
  try {
    const res: any = await recommendApi.today(5)
    recommendations.value = res.recommendations ?? []
  } catch {}
  try { strategies.value = await strategyApi.healthList() } catch {}
  try { account.value = await paperApi.account() } catch {}
})
</script>

<style scoped>
.stat { text-align: center; padding: 10px 0; }
.stat .value { font-size: 32px; font-weight: bold; display: block; }
.stat .label { color: #909399; font-size: 13px; }
.date-bar { font-size: 18px; font-weight: 500; margin-bottom: 16px; }
</style>
