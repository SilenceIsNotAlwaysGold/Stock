<template>
  <div class="news-reco">
    <el-card class="glass toolbar">
      <div class="bar">
        <span class="t">消息面驱动推荐</span>
        <el-select v-model="hours" style="width: 130px">
          <el-option :value="12" label="近 12 小时" />
          <el-option :value="24" label="近 24 小时" />
          <el-option :value="48" label="近 48 小时" />
        </el-select>
        <el-input-number v-model="topN" :min="5" :max="40" :step="5"
                         controls-position="right" style="width: 130px" />
        <el-button type="primary" :loading="loading" @click="load">
          <el-icon><Promotion /></el-icon>&nbsp;获取推荐
        </el-button>
        <span class="hint" v-if="data">
          电报 {{ data.news_count }} 条 · {{ data.generated_at }}
        </span>
      </div>
    </el-card>

    <el-alert v-if="note" :title="note" type="info" show-icon
              :closable="false" style="margin-top: 14px" />

    <!-- 热门板块 -->
    <el-card v-if="data && data.hot_sectors.length" class="glass" style="margin-top: 14px">
      <template #header><span>📰 电报命中热门板块</span></template>
      <div class="sectors">
        <div v-for="h in data.hot_sectors" :key="h.sector" class="sec-chip">
          <div class="sec-top">
            <span class="sec-name">{{ h.sector }}</span>
            <el-tag size="small" type="danger" effect="dark">{{ h.hits }} 条</el-tag>
          </div>
          <div class="sec-news">
            <div v-for="(s, i) in h.sample_news" :key="i" class="sn">· {{ s }}</div>
          </div>
        </div>
      </div>
    </el-card>

    <!-- 推荐个股 -->
    <el-card v-if="data && data.recommendations.length" class="glass" style="margin-top: 14px">
      <template #header>
        <span>🎯 受影响个股（新闻热度 × 量化强度）</span>
      </template>
      <el-table :data="data.recommendations" stripe size="small">
        <el-table-column type="index" label="#" width="48" />
        <el-table-column prop="ts_code" label="代码" width="110" />
        <el-table-column prop="name" label="名称" width="110" />
        <el-table-column label="板块" width="90">
          <template #default="{ row }">
            <el-tag size="small" effect="plain">{{ row.sector }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="综合分" width="90" sortable
                         :sort-method="(a:any,b:any)=>a.total_score-b.total_score">
          <template #default="{ row }">
            <b class="num" :style="{ color: scoreColor(row.total_score) }">
              {{ row.total_score }}
            </b>
          </template>
        </el-table-column>
        <el-table-column label="新闻分" width="80">
          <template #default="{ row }"><span class="num gold">{{ row.news_score }}</span></template>
        </el-table-column>
        <el-table-column label="量化分" width="80">
          <template #default="{ row }"><span class="num accent">{{ row.quant_score }}</span></template>
        </el-table-column>
        <el-table-column label="近5日" width="90">
          <template #default="{ row }">
            <span class="num" :class="row.ret5_pct >= 0 ? 'up' : 'down'">
              {{ row.ret5_pct >= 0 ? '+' : '' }}{{ row.ret5_pct }}%
            </span>
          </template>
        </el-table-column>
        <el-table-column label="换手%" width="80">
          <template #default="{ row }"><span class="num">{{ row.turnover_rate }}</span></template>
        </el-table-column>
        <el-table-column prop="reason" label="推荐理由" min-width="240" show-overflow-tooltip />
      </el-table>
    </el-card>

    <el-empty v-if="data && !data.recommendations.length && !note"
              description="近期电报未命中可交易个股" />
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import { get } from '@/api/client'

const hours = ref(24)
const topN = ref(15)
const loading = ref(false)
const data = ref<any>(null)
const note = ref('')

function scoreColor(s: number) {
  if (s >= 75) return '#ff5c5c'
  if (s >= 60) return '#f0b429'
  if (s >= 45) return '#3ea6ff'
  return '#9aa7b8'
}

async function load() {
  loading.value = true
  note.value = ''
  data.value = null
  try {
    const r: any = await get('/recommend/news-driven', { hours: hours.value, top_n: topN.value })
    if (r.error) { note.value = r.error; return }
    if (r.note) note.value = r.note
    data.value = r
    if (r.recommendations?.length) {
      ElMessage.success(`命中 ${r.hot_sectors.length} 个热门板块，${r.recommendations.length} 只个股`)
    }
  } catch (e: any) {
    note.value = e?.response?.data?.detail || e?.message || '获取失败'
  } finally {
    loading.value = false
  }
}

load()
</script>

<style scoped>
.bar { display: flex; align-items: center; gap: 14px; flex-wrap: wrap; }
.t { font-size: 16px; font-weight: 700; color: var(--text-1); }
.hint { color: var(--text-3); font-size: 12px; }
.sectors { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 12px; }
.sec-chip { background: var(--bg-inset); border: 1px solid var(--border); border-radius: 10px; padding: 12px; }
.sec-top { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
.sec-name { font-size: 15px; font-weight: 700; color: var(--accent); }
.sec-news { display: flex; flex-direction: column; gap: 4px; }
.sn { font-size: 12px; color: var(--text-2); line-height: 1.5; }
.gold { color: var(--gold); }
.accent { color: var(--accent-2); }
</style>
