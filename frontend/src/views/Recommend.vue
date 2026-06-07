<template>
  <div class="recommend">
    <el-card class="glass">
      <template #header>
        <div class="hd">
          <span class="t">个股推荐 · 全市场多策略共振</span>
          <span class="d">数据截止 {{ asOf || date }}<template v-if="total"> · 命中 {{ total }} 只</template></span>
        </div>
      </template>

      <div class="bar">
        <el-button type="primary" :loading="loading" @click="loadRecommendations(true)">
          <el-icon><Refresh /></el-icon>&nbsp;重新生成
        </el-button>
        <el-input v-model="filter" placeholder="筛选代码/名称" clearable
                  style="width: 200px" />
        <span class="hint">仅展示可操作（偏多）信号；评分 0-100，含跨类别共振加权</span>
      </div>

      <el-alert v-if="errMsg" :title="errMsg" type="warning" show-icon
                :closable="false" style="margin: 12px 0" />

      <el-skeleton v-if="loading && !rows.length" :rows="6" animated style="margin-top:14px" />

      <el-empty v-else-if="!loading && !rows.length && !errMsg"
                description="暂无可操作推荐（多策略未形成偏多共振）" />

      <el-table v-else :data="filtered" stripe size="small"
                @expand-change="() => {}" row-key="ts_code">
        <el-table-column type="expand">
          <template #default="{ row }">
            <div class="sig-wrap">
              <div v-for="(s, i) in row.signals" :key="i" class="sig">
                <el-tag size="small"
                        :type="s.action === 'BUY' ? 'danger' : s.action === 'SELL' ? 'success' : 'info'"
                        effect="plain">{{ s.action }}</el-tag>
                <b>{{ s.strategy }}</b>
                <span class="sig-cat">[{{ s.category }}]</span>
                <span class="sig-cf">置信 {{ (s.confidence * 100).toFixed(0) }}%</span>
                <span class="sig-rs">{{ s.reason }}</span>
              </div>
            </div>
          </template>
        </el-table-column>
        <el-table-column type="index" label="#" width="50" />
        <el-table-column prop="ts_code" label="代码" width="115" />
        <el-table-column prop="name" label="名称" width="110" />
        <el-table-column label="综合评分" width="110" sortable
                         :sort-method="(a:any,b:any)=>a.score-b.score">
          <template #default="{ row }">
            <b class="num" :style="{ color: scoreColor(row.score) }">{{ row.score }}</b>
          </template>
        </el-table-column>
        <el-table-column label="信号" width="80">
          <template #default="{ row }">
            <el-tag :type="row.action === 'BUY' ? 'danger' : row.action === 'SELL' ? 'success' : 'info'"
                    size="small" effect="dark">{{ row.action }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="最新涨跌" width="100">
          <template #default="{ row }">
            <span class="num" :class="row.today_chg_pct >= 0 ? 'up' : 'down'">
              {{ row.today_chg_pct >= 0 ? '+' : '' }}{{ row.today_chg_pct }}%
            </span>
          </template>
        </el-table-column>
        <el-table-column label="买/卖策略数" width="120">
          <template #default="{ row }">
            <span class="up num">{{ row.buy_count }}</span> /
            <span class="down num">{{ row.sell_count }}</span>
          </template>
        </el-table-column>
        <el-table-column label="共振" width="80">
          <template #default="{ row }">
            <el-tag v-if="row.resonance" type="warning" size="small" effect="dark">共振</el-tag>
            <span v-else class="muted">—</span>
          </template>
        </el-table-column>
        <el-table-column label="" min-width="60">
          <template #default><span class="muted exp-tip">▸ 展开看各策略</span></template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { recommendApi } from '@/api'

const rows = ref<any[]>([])
const loading = ref(false)
const date = ref('')
const asOf = ref('')
const total = ref(0)
const errMsg = ref('')
const filter = ref('')

const filtered = computed(() => {
  const q = filter.value.trim().toLowerCase()
  if (!q) return rows.value
  return rows.value.filter((r) =>
    r.ts_code.toLowerCase().includes(q) || (r.name || '').toLowerCase().includes(q))
})

function scoreColor(s: number) {
  if (s >= 75) return '#ff5c5c'
  if (s >= 62) return '#f0b429'
  if (s >= 50) return '#3ea6ff'
  return '#9aa7b8'
}

async function loadRecommendations(refresh = false) {
  loading.value = true
  errMsg.value = ''
  try {
    const res: any = await recommendApi.today(50, refresh)
    rows.value = res.recommendations ?? []
    date.value = res.date ?? ''
    asOf.value = res.as_of ?? ''
    total.value = res.count ?? rows.value.length
    if (refresh) ElMessage.success(`已生成 ${total.value} 只可操作推荐`)
    if (!rows.value.length) errMsg.value = ''
  } catch (e: any) {
    errMsg.value = e?.response?.data?.detail || e?.message ||
      '推荐生成失败（首次全市场计算较慢，请点「重新生成」重试）'
  } finally {
    loading.value = false
  }
}

onMounted(() => loadRecommendations(false))
</script>

<style scoped>
.hd { display: flex; justify-content: space-between; align-items: center; }
.t { font-size: 16px; font-weight: 700; color: var(--text-1); }
.d { font-size: 13px; color: var(--text-3); }
.bar { display: flex; align-items: center; gap: 14px; flex-wrap: wrap; margin-bottom: 8px; }
.hint { color: var(--text-3); font-size: 12px; }
.muted { color: var(--text-3); }
.exp-tip { font-size: 12px; }
.sig-wrap { padding: 10px 18px; display: flex; flex-direction: column; gap: 6px; }
.sig { display: flex; align-items: center; gap: 10px; font-size: 12px; color: var(--text-2); }
.sig b { color: var(--text-1); }
.sig-cat { color: var(--text-3); }
.sig-cf { color: var(--accent-2); }
.sig-rs { color: var(--text-2); }
</style>
