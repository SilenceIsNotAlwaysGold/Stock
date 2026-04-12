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
            <span class="value">{{ overview.total_candidates ?? recommendations.length }}</span>
            <span class="label">推荐股票</span>
          </div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="hover">
          <template #header>模拟盘</template>
          <div class="stat">
            <span class="value" :style="{ color: (overview.total_pnl ?? account.total_pnl) >= 0 ? '#67c23a' : '#f56c6c' }">
              {{ (overview.total_pnl ?? account.total_pnl)?.toFixed(2) ?? '--' }}
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

    <el-card style="margin-top: 16px">
      <template #header><span>今日候选 TOP 3</span></template>
      <el-table :data="topCandidates" size="small" stripe empty-text="今日暂无候选">
        <el-table-column prop="ts_code" label="代码" width="100" />
        <el-table-column prop="stock_name" label="名称" width="90" />
        <el-table-column prop="score" label="评分" width="80">
          <template #default="{ row }">
            <span :style="{ fontWeight: 700, color: row.score >= 50 ? '#67c23a' : '#e6a23c' }">
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
import { ref, onMounted, computed } from 'vue'
import { emotionApi, recommendApi, strategyApi, paperApi, t1Api } from '@/api'

const emotion = ref<any>({})
const recommendations = ref<any[]>([])
const strategies = ref<any[]>([])
const account = ref<any>({})
const overview = ref<any>({})
const topCandidates = ref<any[]>([])
const recentTrades = ref<any[]>([])

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

async function loadDashboard() {
  try {
    const r: any = await t1Api.dashboard()
    if (r.overview) {
      overview.value = r.overview
    }
    topCandidates.value = r.top_candidates || []
    recentTrades.value = r.recent_trades || []
  } catch (e) {
    console.error('加载仪表盘数据失败:', e)
  }
}

onMounted(async () => {
  try { emotion.value = await emotionApi.today() } catch (e) { console.error('加载市场情绪失败:', e) }
  try {
    const res: any = await recommendApi.today(5)
    recommendations.value = res.recommendations ?? []
  } catch (e) { console.error('加载推荐失败:', e) }
  try { strategies.value = await strategyApi.healthList() } catch (e) { console.error('加载策略失败:', e) }
  try { account.value = await paperApi.account() } catch (e) { console.error('加载账户失败:', e) }
  loadDashboard()
})
</script>

<style scoped>
.stat { text-align: center; padding: 10px 0; }
.stat .value { font-size: 32px; font-weight: bold; display: block; }
.stat .label { color: #909399; font-size: 13px; }
.date-bar { font-size: 18px; font-weight: 500; margin-bottom: 16px; }
.up { color: #f56c6c; }
.down { color: #67c23a; }
</style>
