<template>
  <div class="sector-page">
    <!-- 参数栏 -->
    <el-card class="toolbar">
      <el-row :gutter="16" align="middle">
        <el-col :span="5">
          <el-form-item label="观察窗口" style="margin:0">
            <el-select v-model="params.window_days" style="width:100%">
              <el-option label="3 天" :value="3" />
              <el-option label="5 天" :value="5" />
              <el-option label="10 天" :value="10" />
              <el-option label="20 天" :value="20" />
            </el-select>
          </el-form-item>
        </el-col>
        <el-col :span="4">
          <el-form-item label="推荐板块" style="margin:0">
            <el-input-number
              v-model="params.top_n" :min="1" :max="10"
              controls-position="right" style="width:100%"
            />
          </el-form-item>
        </el-col>
        <el-col :span="4">
          <el-form-item label="每板块个股" style="margin:0">
            <el-input-number
              v-model="params.stocks_per_sector" :min="1" :max="5"
              controls-position="right" style="width:100%"
            />
          </el-form-item>
        </el-col>
        <el-col :span="3">
          <el-form-item label="LLM" style="margin:0">
            <el-switch v-model="params.with_llm" />
          </el-form-item>
        </el-col>
        <el-col :span="4">
          <el-button type="primary" :loading="loading" @click="load" style="width:100%">
            <el-icon><Refresh /></el-icon>&nbsp;{{ loading ? '获取中...' : '获取推荐' }}
          </el-button>
        </el-col>
        <el-col :span="4" style="color:#909399;font-size:12px;text-align:right">
          {{ report.generated_at ? '🕒 ' + report.generated_at.split(' ')[1] : '约 30s' }}
        </el-col>
      </el-row>
    </el-card>

    <!-- 空状态 -->
    <el-empty v-if="!loading && !report.recommendations?.length" description="点击「获取推荐」拉取实时板块数据" style="margin-top:60px" />

    <!-- 板块卡片列表 -->
    <div v-for="(item, idx) in report.recommendations" :key="idx" class="sector-block">
      <!-- 板块头 -->
      <el-card shadow="hover" class="sector-header-card">
        <el-row :gutter="20" align="middle">
          <el-col :span="1">
            <div class="rank-badge">{{ idx + 1 }}</div>
          </el-col>
          <el-col :span="5">
            <div class="sector-name">{{ item.sector.name }}</div>
            <el-tag :type="trendTag(item.sector.trend)" size="small" style="margin-top:4px">
              {{ item.sector.trend }}
            </el-tag>
          </el-col>
          <el-col :span="3" class="stat-col">
            <div class="stat-val" :class="item.sector.stats.period_return_pct >= 0 ? 'up' : 'down'">
              {{ item.sector.stats.period_return_pct >= 0 ? '+' : '' }}{{ item.sector.stats.period_return_pct?.toFixed(2) }}%
            </div>
            <div class="stat-lbl">{{ params.window_days }}日涨幅</div>
          </el-col>
          <el-col :span="3" class="stat-col">
            <div class="stat-val" :class="item.sector.stats.today_change_pct >= 0 ? 'up' : 'down'">
              {{ item.sector.stats.today_change_pct >= 0 ? '+' : '' }}{{ item.sector.stats.today_change_pct?.toFixed(2) }}%
            </div>
            <div class="stat-lbl">今日涨幅</div>
          </el-col>
          <el-col :span="3" class="stat-col">
            <div class="stat-val" style="color:#e6a23c">
              {{ item.sector.stats.net_inflow_bn?.toFixed(1) }} 亿
            </div>
            <div class="stat-lbl">净流入</div>
          </el-col>
          <el-col :span="3" class="stat-col">
            <div class="stat-val">{{ item.sector.stock_count }} 家</div>
            <div class="stat-lbl">成分股</div>
          </el-col>
          <el-col :span="3" class="stat-col">
            <div class="stat-val" style="color:#f56c6c">{{ item.sector.leader_stock }}</div>
            <div class="stat-lbl">
              龙头 {{ item.sector.leader_change_pct >= 0 ? '+' : '' }}{{ item.sector.leader_change_pct?.toFixed(2) }}%
            </div>
          </el-col>
          <el-col :span="3" class="stat-col">
            <el-progress
              type="circle"
              :percentage="Math.round(item.sector.heat_score)"
              :color="heatColor(item.sector.heat_score)"
              :width="56"
              :stroke-width="6"
            />
            <div class="stat-lbl">热度</div>
          </el-col>
        </el-row>
      </el-card>

      <!-- LLM 分析 -->
      <el-card v-if="item.analysis" class="llm-card" shadow="never">
        <el-row :gutter="16">
          <el-col :span="6">
            <div class="llm-label">催化剂</div>
            <div class="llm-val">{{ item.analysis.catalyst }}</div>
          </el-col>
          <el-col :span="4">
            <div class="llm-label">行情阶段</div>
            <el-tag :type="stageTag(item.analysis.stage)" effect="dark">{{ item.analysis.stage }}</el-tag>
          </el-col>
          <el-col :span="4">
            <div class="llm-label">操作方向</div>
            <el-tag :type="item.analysis.pick_direction === '积极介入' ? 'success' : item.analysis.pick_direction === '谨慎观望' ? 'warning' : 'danger'" effect="dark">
              {{ item.analysis.pick_direction }}
            </el-tag>
          </el-col>
          <el-col :span="10">
            <div class="llm-label">风险提示</div>
            <div class="llm-risk">{{ item.analysis.risks }}</div>
          </el-col>
        </el-row>
        <div class="llm-summary">{{ item.analysis.summary }}</div>
      </el-card>

      <!-- 个股推荐 -->
      <el-card class="stocks-card" shadow="never">
        <template #header>
          <span style="font-size:13px;color:#606266">板块内精选个股</span>
        </template>
        <el-table :data="item.stocks" size="small" stripe>
          <el-table-column label="名称" width="100">
            <template #default="{ row }">
              <span :class="row.role === '龙头' ? 'leader-stock' : ''">{{ row.name }}</span>
              <el-tag v-if="row.role === '龙头'" size="small" type="danger" effect="dark" style="margin-left:4px">龙</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="今日涨跌" width="100">
            <template #default="{ row }">
              <span :class="row.today_change_pct >= 0 ? 'up' : 'down'" style="font-weight:600">
                {{ row.today_change_pct >= 0 ? '+' : '' }}{{ row.today_change_pct?.toFixed(2) }}%
              </span>
            </template>
          </el-table-column>
          <el-table-column label="换手率" width="90">
            <template #default="{ row }">{{ row.turnover_rate ? row.turnover_rate?.toFixed(2) + '%' : '--' }}</template>
          </el-table-column>
          <el-table-column label="评分" width="80">
            <template #default="{ row }">
              <span :style="{ color: row.score >= 70 ? '#67c23a' : '#e6a23c', fontWeight: 700 }">{{ row.score?.toFixed(0) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="推荐理由" prop="reason" />
        </el-table>
      </el-card>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive } from 'vue'
import { ElMessage } from 'element-plus'
import { get } from '@/api/client'

const loading = ref(false)
const report = ref<any>({ recommendations: [] })
const params = reactive({ window_days: 5, top_n: 3, stocks_per_sector: 2, with_llm: false })

async function load() {
  loading.value = true
  try {
    const res = await get('/sector/recommend', params)
    report.value = res
    if (!res.recommendations?.length) ElMessage.warning('未找到符合条件的热门板块')
    else ElMessage.success(`获取到 ${res.total_sectors} 个热门板块`)
  } catch (e: any) {
    ElMessage.error('获取失败：' + (e.response?.data?.detail || e.message))
  } finally {
    loading.value = false
  }
}

function trendTag(trend: string) {
  if (trend === '强势上涨') return 'danger'
  if (trend === '升温') return 'warning'
  if (trend === '震荡') return 'info'
  return ''
}

function stageTag(stage: string) {
  if (stage === '启动期') return 'success'
  if (stage === '爆发期') return 'danger'
  if (stage === '高位震荡') return 'warning'
  return 'info'
}

function heatColor(score: number) {
  if (score >= 70) return '#f56c6c'
  if (score >= 50) return '#e6a23c'
  return '#409eff'
}
</script>

<style scoped>
.sector-page { padding-bottom: 40px; }
.toolbar { margin-bottom: 16px; }
.sector-block { margin-bottom: 16px; }
.sector-header-card { border-left: 4px solid #409eff; }
.rank-badge {
  width: 32px; height: 32px; border-radius: 50%;
  background: #409eff; color: #fff;
  display: flex; align-items: center; justify-content: center;
  font-size: 16px; font-weight: bold;
}
.sector-name { font-size: 18px; font-weight: 700; }
.stat-col { text-align: center; }
.stat-val { font-size: 18px; font-weight: 700; }
.stat-lbl { font-size: 11px; color: #909399; margin-top: 2px; }
.up { color: #f56c6c; }
.down { color: #67c23a; }
.llm-card {
  background: #fafafa; border-top: none; border-radius: 0;
  border: 1px solid #ebeef5; border-top: none;
}
.llm-label { font-size: 11px; color: #909399; margin-bottom: 6px; }
.llm-val { font-size: 13px; font-weight: 600; }
.llm-risk { font-size: 12px; color: #e6a23c; }
.llm-summary { margin-top: 10px; font-size: 13px; color: #303133; line-height: 1.8; border-top: 1px solid #eee; padding-top: 8px; }
.stocks-card { border-top: none; border-radius: 0 0 4px 4px; }
.leader-stock { font-weight: 700; color: #f56c6c; }
</style>
