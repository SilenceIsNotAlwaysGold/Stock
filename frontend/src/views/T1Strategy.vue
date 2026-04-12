<template>
  <div class="t1-strategy">
    <!-- 顶部统计卡片 -->
    <el-row :gutter="16" class="stat-cards">
      <el-col :span="6">
        <el-card shadow="hover" class="stat-card">
          <div class="stat">
            <div class="stat-icon" style="background: #ecf5ff"><el-icon :size="28" color="#409eff"><Search /></el-icon></div>
            <div class="stat-info">
              <span class="value">{{ overview.candidates_today }}</span>
              <span class="label">今日候选</span>
            </div>
          </div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="hover" class="stat-card">
          <div class="stat">
            <div class="stat-icon" style="background: #fdf6ec"><el-icon :size="28" color="#e6a23c"><Briefcase /></el-icon></div>
            <div class="stat-info">
              <span class="value">{{ overview.positions_holding }}</span>
              <span class="label">当前持仓</span>
            </div>
          </div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="hover" class="stat-card">
          <div class="stat">
            <div class="stat-icon" style="background: #f0f9eb"><el-icon :size="28" color="#67c23a"><TrendCharts /></el-icon></div>
            <div class="stat-info">
              <span class="value" :class="overview.win_rate >= 0.5 ? 'up' : 'down'">
                {{ (overview.win_rate * 100).toFixed(1) }}%
              </span>
              <span class="label">总胜率 ({{ overview.total_trades }}笔)</span>
            </div>
          </div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="hover" class="stat-card">
          <div class="stat">
            <div class="stat-icon" style="background: #fef0f0"><el-icon :size="28" color="#f56c6c"><Wallet /></el-icon></div>
            <div class="stat-info">
              <span class="value" :class="overview.total_pnl >= 0 ? 'up' : 'down'">
                {{ overview.total_pnl >= 0 ? '+' : '' }}{{ overview.total_pnl.toFixed(2) }}
              </span>
              <span class="label">累计盈亏</span>
            </div>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <!-- Tab 页 -->
    <el-card style="margin-top: 16px">
      <el-tabs v-model="activeTab" @tab-change="onTabChange">
        <el-tab-pane label="候选股监控" name="candidates">
          <div style="margin-bottom: 12px; display: flex; gap: 12px; align-items: center">
            <el-button type="warning" :loading="syncing" @click="doSync"><el-icon><Refresh /></el-icon>&nbsp;同步数据</el-button>
            <el-button type="primary" :loading="scanning" @click="doScan"><el-icon><Search /></el-icon>&nbsp;{{ scanning ? `扫描中 (${scanElapsed}s)` : '扫描选股' }}</el-button>
            <el-select v-model="filterCriterion" placeholder="全部条件" clearable style="width: 150px" @change="loadCandidates">
              <el-option label="v4多维评分" value="v4_multidim" />
            </el-select>
            <span v-if="syncMsg" style="font-size: 12px; color: #909399">{{ syncMsg }}</span>
          </div>
          <el-table :data="pagedCandidates" stripe v-loading="scanning" size="small" :row-class-name="candidateRowClass" empty-text="暂无候选股，请先同步数据再扫描选股">
            <el-table-column prop="ts_code" label="代码" width="100" />
            <el-table-column prop="stock_name" label="名称" width="90">
              <template #default="{ row }">
                <el-link type="primary" @click="openDetail(row)">{{ row.stock_name }}</el-link>
              </template>
            </el-table-column>
            <el-table-column prop="criterion" label="条件" width="95">
              <template #default="{ row }"><el-tag :type="criterionTagType(row.criterion)" size="small" effect="dark">{{ criterionLabel(row.criterion) }}</el-tag></template>
            </el-table-column>
            <el-table-column prop="score" label="综合分" width="80" sortable>
              <template #default="{ row }">
                <span :style="{ fontWeight: 700, color: row.score >= 70 ? '#67c23a' : row.score >= 50 ? '#e6a23c' : '#909399' }">
                  {{ row.score?.toFixed(1) }}
                </span>
              </template>
            </el-table-column>
            <el-table-column label="技术" width="55" sortable prop="tech_score">
              <template #default="{ row }">
                <span style="font-size: 12px">{{ row.tech_score?.toFixed(0) ?? '-' }}</span>
              </template>
            </el-table-column>
            <el-table-column label="资金" width="55" sortable prop="capital_score">
              <template #default="{ row }">
                <span style="font-size: 12px">{{ row.capital_score?.toFixed(0) ?? '-' }}</span>
              </template>
            </el-table-column>
            <el-table-column label="基本" width="55" sortable prop="fundamental_score">
              <template #default="{ row }">
                <span style="font-size: 12px">{{ row.fundamental_score?.toFixed(0) ?? '-' }}</span>
              </template>
            </el-table-column>
            <el-table-column label="板块" width="55" sortable prop="sector_score">
              <template #default="{ row }">
                <span style="font-size: 12px">{{ row.sector_score?.toFixed(0) ?? '-' }}</span>
              </template>
            </el-table-column>
            <el-table-column label="市场" width="55" sortable prop="market_score">
              <template #default="{ row }">
                <span style="font-size: 12px">{{ row.market_score?.toFixed(0) ?? '-' }}</span>
              </template>
            </el-table-column>
            <el-table-column prop="close_price" label="收盘价" width="85" />
            <el-table-column prop="change_pct" label="涨跌%" width="85" sortable>
              <template #default="{ row }">
                <span :class="(row.change_pct ?? 0) >= 0 ? 'up' : 'down'" style="font-weight: 600">{{ row.change_pct != null ? ((row.change_pct >= 0 ? '+' : '') + row.change_pct.toFixed(2) + '%') : '-' }}</span>
              </template>
            </el-table-column>
            <el-table-column prop="volume_ratio" label="量比" width="70">
              <template #default="{ row }">
                <span :style="{ fontWeight: (row.volume_ratio ?? 0) >= 3 ? '700' : '400', color: (row.volume_ratio ?? 0) >= 3 ? '#e6a23c' : '' }">{{ row.volume_ratio?.toFixed(1) ?? '-' }}</span>
              </template>
            </el-table-column>
            <el-table-column prop="turnover_rate" label="换手%" width="75">
              <template #default="{ row }">{{ row.turnover_rate != null ? row.turnover_rate.toFixed(1) + '%' : '-' }}</template>
            </el-table-column>
            <el-table-column prop="reason" label="选股理由" min-width="140" show-overflow-tooltip />
            <el-table-column label="操作" width="90" fixed="right">
              <template #default="{ row }">
                <el-button v-if="row.status === 'pending'" type="success" size="small" @click="doBuy(row)">买入</el-button>
                <el-tag v-else size="small" :type="row.status === 'bought' ? 'success' : 'info'">{{ row.status === 'bought' ? '已买' : row.status }}</el-tag>
              </template>
            </el-table-column>
          </el-table>
          <el-pagination v-if="candidates.length > candidatePageSize" style="margin-top: 12px; justify-content: flex-end" layout="total, sizes, prev, pager, next" :total="candidates.length" :page-size="candidatePageSize" :page-sizes="[10, 20, 50]" :current-page="candidatePage" @current-change="(p: number) => candidatePage = p" @size-change="(s: number) => { candidatePageSize = s; candidatePage = 1 }" />
        </el-tab-pane>

        <el-tab-pane label="持仓管理" name="positions">
          <el-table :data="positions" stripe size="small" empty-text="暂无持仓">
            <el-table-column prop="ts_code" label="代码" width="100" />
            <el-table-column prop="stock_name" label="名称" width="90" />
            <el-table-column prop="buy_price" label="买入价" width="85">
              <template #default="{ row }">{{ row.buy_price?.toFixed(2) }}</template>
            </el-table-column>
            <el-table-column prop="quantity" label="数量" width="75" />
            <el-table-column prop="criterion" label="条件" width="95">
              <template #default="{ row }"><el-tag :type="criterionTagType(row.criterion)" size="small" effect="dark">{{ criterionLabel(row.criterion) }}</el-tag></template>
            </el-table-column>
            <el-table-column prop="buy_date" label="买入日期" width="110" />
            <el-table-column label="止盈价" width="85">
              <template #default="{ row }"><span class="up">{{ (row.buy_price * 1.05).toFixed(2) }}</span></template>
            </el-table-column>
            <el-table-column label="止损价" width="85">
              <template #default="{ row }"><span class="down">{{ (row.buy_price * 0.97).toFixed(2) }}</span></template>
            </el-table-column>
            <el-table-column label="操作" width="100" fixed="right">
              <template #default="{ row }"><el-button type="danger" size="small" @click="doSell(row)">卖出</el-button></template>
            </el-table-column>
          </el-table>
        </el-tab-pane>

        <el-tab-pane label="交易记录" name="trades">
          <el-table :data="trades" stripe size="small" empty-text="暂无交易记录">
            <el-table-column prop="ts_code" label="代码" width="100" />
            <el-table-column prop="stock_name" label="名称" width="80" />
            <el-table-column prop="criterion" label="条件" width="90">
              <template #default="{ row }"><el-tag :type="criterionTagType(row.criterion)" size="small" effect="dark">{{ criterionLabel(row.criterion) }}</el-tag></template>
            </el-table-column>
            <el-table-column prop="buy_date" label="买入日" width="100" />
            <el-table-column prop="buy_price" label="买入价" width="80" />
            <el-table-column prop="sell_date" label="卖出日" width="100" />
            <el-table-column prop="sell_price" label="卖出价" width="80" />
            <el-table-column prop="sell_reason" label="原因" width="90">
              <template #default="{ row }"><el-tag :type="sellReasonType(row.sell_reason)" size="small">{{ sellReasonLabel(row.sell_reason) }}</el-tag></template>
            </el-table-column>
            <el-table-column prop="pnl_pct" label="盈亏%" width="90" sortable>
              <template #default="{ row }"><span :class="row.pnl_pct >= 0 ? 'up' : 'down'" style="font-weight: 600">{{ row.pnl_pct >= 0 ? '+' : '' }}{{ row.pnl_pct.toFixed(2) }}%</span></template>
            </el-table-column>
            <el-table-column prop="is_win" label="胜负" width="65">
              <template #default="{ row }"><el-tag :type="row.is_win ? 'success' : 'danger'" size="small" effect="dark">{{ row.is_win ? '盈' : '亏' }}</el-tag></template>
            </el-table-column>
          </el-table>
          <el-pagination v-if="tradePagination.total > 0" style="margin-top: 12px; justify-content: flex-end" layout="total, prev, pager, next" :total="tradePagination.total" :page-size="tradePagination.pageSize" :current-page="tradePagination.page" @current-change="onTradePageChange" />
        </el-tab-pane>

        <el-tab-pane label="策略统计" name="stats">
          <T1StatsChart :data="criteriaStats" :height="350" />
          <el-table :data="criteriaStats" stripe size="small" style="margin-top: 16px" empty-text="暂无统计数据">
            <el-table-column prop="criterion" label="条件" width="120">
              <template #default="{ row }"><el-tag :type="criterionTagType(row.criterion)" size="small" effect="dark">{{ criterionLabel(row.criterion) }}</el-tag></template>
            </el-table-column>
            <el-table-column prop="total_trades" label="总交易" width="80" />
            <el-table-column prop="win_count" label="盈利" width="70" />
            <el-table-column prop="win_rate" label="胜率" width="90">
              <template #default="{ row }"><span :class="row.win_rate >= 0.5 ? 'up' : 'down'" style="font-weight: 600">{{ (row.win_rate * 100).toFixed(1) }}%</span></template>
            </el-table-column>
            <el-table-column prop="avg_pnl_pct" label="平均盈亏%" width="100">
              <template #default="{ row }"><span :class="row.avg_pnl_pct >= 0 ? 'up' : 'down'">{{ row.avg_pnl_pct.toFixed(2) }}%</span></template>
            </el-table-column>
            <el-table-column prop="max_pnl_pct" label="最大盈利%" width="100">
              <template #default="{ row }"><span class="up">{{ row.max_pnl_pct?.toFixed(2) ?? '-' }}%</span></template>
            </el-table-column>
            <el-table-column prop="min_pnl_pct" label="最大亏损%" width="100">
              <template #default="{ row }"><span class="down">{{ row.min_pnl_pct?.toFixed(2) ?? '-' }}%</span></template>
            </el-table-column>
          </el-table>
        </el-tab-pane>
      </el-tabs>
    </el-card>
  </div>

  <!-- 候选股详情弹窗 -->
  <el-dialog v-model="showDetail" :title="`${selectedCandidate?.stock_name} (${selectedCandidate?.ts_code})`" width="500px" destroy-on-close>
    <template v-if="selectedCandidate">
      <div style="text-align: center; margin-bottom: 16px">
        <span style="font-size: 32px; font-weight: 700" :style="{ color: (selectedCandidate.score ?? 0) >= 50 ? '#67c23a' : '#e6a23c' }">
          {{ selectedCandidate.score?.toFixed(1) }}
        </span>
        <span style="font-size: 14px; color: #909399"> / 100 分</span>
      </div>
      <div ref="radarChartRef" style="width: 350px; height: 300px; margin: 0 auto"></div>
      <el-descriptions :column="2" size="small" border style="margin-top: 16px">
        <el-descriptions-item label="技术面">{{ selectedCandidate.tech_score?.toFixed(1) }} / 30</el-descriptions-item>
        <el-descriptions-item label="资金面">{{ selectedCandidate.capital_score?.toFixed(1) }} / 25</el-descriptions-item>
        <el-descriptions-item label="基本面">{{ selectedCandidate.fundamental_score?.toFixed(1) }} / 15</el-descriptions-item>
        <el-descriptions-item label="板块面">{{ selectedCandidate.sector_score?.toFixed(1) }} / 15</el-descriptions-item>
        <el-descriptions-item label="市场面">{{ selectedCandidate.market_score?.toFixed(1) }} / 15</el-descriptions-item>
        <el-descriptions-item label="收盘价">{{ selectedCandidate.close_price }}</el-descriptions-item>
      </el-descriptions>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted, computed, nextTick } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import * as echarts from 'echarts'
import { t1Api } from '@/api'
import type { T1Candidate, T1Position, T1Trade, T1CriteriaStats, T1Overview } from '@/types'
import T1StatsChart from '@/components/T1StatsChart.vue'

const activeTab = ref('candidates')
const scanning = ref(false)
const syncing = ref(false)
const scanElapsed = ref(0)
let scanTimer: ReturnType<typeof setInterval> | null = null
const syncMsg = ref('')
const filterCriterion = ref('')
const overview = reactive<T1Overview>({ candidates_today: 0, positions_holding: 0, total_trades: 0, win_rate: 0, total_pnl: 0 })
const candidates = ref<T1Candidate[]>([])
const positions = ref<T1Position[]>([])
const trades = ref<T1Trade[]>([])
const criteriaStats = ref<T1CriteriaStats[]>([])
const tradePagination = reactive({ page: 1, pageSize: 20, total: 0 })
const candidatePage = ref(1)
const candidatePageSize = ref(10)

const showDetail = ref(false)
const selectedCandidate = ref<T1Candidate | null>(null)
const radarChartRef = ref<HTMLElement | null>(null)

function openDetail(row: T1Candidate) {
  selectedCandidate.value = row
  showDetail.value = true
  nextTick(() => {
    if (radarChartRef.value) {
      const chart = echarts.init(radarChartRef.value)
      chart.setOption({
        radar: {
          indicator: [
            { name: '技术', max: 30 },
            { name: '资金', max: 25 },
            { name: '基本面', max: 15 },
            { name: '板块', max: 15 },
            { name: '市场', max: 15 },
          ],
          shape: 'circle',
          splitArea: { areaStyle: { color: ['rgba(64,158,255,0.05)', 'rgba(64,158,255,0.1)'] } },
        },
        series: [{
          type: 'radar',
          data: [{
            value: [
              row.tech_score ?? 0,
              row.capital_score ?? 0,
              row.fundamental_score ?? 0,
              row.sector_score ?? 0,
              row.market_score ?? 0,
            ],
            areaStyle: { color: 'rgba(64, 158, 255, 0.3)' },
            lineStyle: { color: '#409eff' },
            itemStyle: { color: '#409eff' },
          }],
        }],
      })
    }
  })
}

const pagedCandidates = computed(() => {
  const start = (candidatePage.value - 1) * candidatePageSize.value
  return candidates.value.slice(start, start + candidatePageSize.value)
})

const CRITERION_LABELS: Record<string, string> = {
  limit_reopen: '涨停回封',
  tail_surge: '尾盘拉升',
  sector_leader: '板块龙头',
  v4_multidim: 'v4评分',
}
const SELL_REASON_LABELS: Record<string, string> = {
  phase1_take_profit: '高开止盈',
  phase1_stop_loss: '低开止损',
  phase2_take_profit: '盘中止盈',
  phase2_stop_loss: '盘中止损',
  phase3_lock_profit: '收盘锁利',
  phase3_stop_loss: '收盘止损',
  phase4_timeout: '兜底退出',
  limit_up_hold: '涨停持有',
  take_profit: '止盈',
  stop_loss: '止损',
  timeout_sell: '超时卖出',
  manual: '手动',
}
function criterionLabel(c: string) { return CRITERION_LABELS[c] || c }
function criterionTagType(c: string) {
  return ({ limit_reopen: 'danger', tail_surge: 'warning', sector_leader: '', v4_multidim: 'success' } as Record<string, string>)[c] || 'info'
}
function sellReasonLabel(r: string) { return SELL_REASON_LABELS[r] || r }
function sellReasonType(r: string) { return { take_profit: 'success', stop_loss: 'danger', timeout_sell: 'warning', manual: 'info' }[r] || '' }

async function loadCandidates() {
  try {
    const r = await t1Api.candidates('', filterCriterion.value)
    candidates.value = r.items || []
  } catch (e) { console.error('加载候选失败:', e) }
}
async function loadPositions() {
  try {
    const r = await t1Api.positions()
    positions.value = r.items || []
  } catch (e) { console.error('加载持仓失败:', e) }
}
async function loadTrades(page = 1) {
  try {
    const r = await t1Api.trades(page, tradePagination.pageSize)
    trades.value = r.items || []
    tradePagination.total = r.total || 0
    tradePagination.page = page
  } catch (e) { console.error('加载交易记录失败:', e) }
}
async function loadStats() {
  try {
    const r = await t1Api.stats()
    if (r.overview) Object.assign(overview, r.overview)
    criteriaStats.value = r.criteria || []
  } catch (e) { console.error('加载统计失败:', e) }
}

async function doSync() {
  syncing.value = true; syncMsg.value = '正在同步 Tushare 数据...'
  try {
    const r = await t1Api.syncData(50, 30)
    if (r.success) {
      syncMsg.value = `同步完成: ${r.stocks_synced}新股票, ${r.bars_synced}条日线`
      ElMessage.success('数据同步完成')
    } else {
      syncMsg.value = ''
      ElMessage.error(r.error || '同步失败')
    }
  } catch (e: any) {
    syncMsg.value = ''
    ElMessage.error(e?.response?.data?.error?.message || e?.message || '同步失败，请稍后重试')
  } finally {
    syncing.value = false
  }
}
async function doScan() {
  scanning.value = true
  scanElapsed.value = 0
  scanTimer = setInterval(() => { scanElapsed.value++ }, 1000)
  try {
    const r = await t1Api.scan()
    ElMessage.success(`扫描完成，发现 ${r.found || 0} 只候选股`)
    await loadCandidates()
    await loadStats()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.error?.message || e?.message || '扫描失败，请稍后重试')
  } finally {
    scanning.value = false
    if (scanTimer) { clearInterval(scanTimer); scanTimer = null }
  }
}
async function doBuy(row: T1Candidate) {
  try {
    await ElMessageBox.confirm(`确认买入 ${row.stock_name}(${row.ts_code})？\n收盘价: ${row.close_price}  数量: 100股`, '买入确认', { type: 'info' })
    await t1Api.buy(row.id)
    ElMessage.success('买入成功')
    await loadCandidates(); await loadPositions(); await loadStats()
  } catch (e: any) {
    if (e !== 'cancel' && e?.type !== 'cancel') {
      ElMessage.error(e?.response?.data?.error?.message || e?.message || '买入操作失败')
    }
  }
}
async function doSell(row: T1Position) {
  try {
    const tp = (row.buy_price * 1.05).toFixed(2)
    const sl = (row.buy_price * 0.97).toFixed(2)
    const result: any = await ElMessageBox.prompt(
      `${row.stock_name}(${row.ts_code})\n买入价: ${row.buy_price}  止盈: ${tp}  止损: ${sl}`,
      '卖出 - 输入卖出价格',
      { inputValue: String(row.buy_price), inputPattern: /^\d+(\.\d+)?$/, inputErrorMessage: '请输入有效价格' }
    )
    const r = await t1Api.sell(row.id, parseFloat(result.value))
    ElMessage.success(`卖出成功，盈亏 ${r.pnl_pct}%`)
    await loadPositions(); await loadTrades(); await loadStats()
  } catch (e: any) {
    if (e !== 'cancel' && e?.type !== 'cancel') {
      ElMessage.error(e?.response?.data?.error?.message || e?.message || '卖出操作失败')
    }
  }
}
function onTradePageChange(page: number) { loadTrades(page) }
function candidateRowClass({ row }: { row: T1Candidate }) { return row.score >= 70 ? 'high-score-row' : '' }
function onTabChange(tab: string) {
  if (tab === 'candidates') loadCandidates()
  else if (tab === 'positions') loadPositions()
  else if (tab === 'trades') loadTrades()
  else if (tab === 'stats') loadStats()
}
onMounted(() => { loadStats(); loadCandidates(); loadPositions(); loadTrades() })
</script>

<style scoped>
.stat-cards .stat-card { border-radius: 8px; }
.stat-cards .stat-card :deep(.el-card__body) { padding: 16px 20px; }
.stat { display: flex; align-items: center; gap: 16px; }
.stat-icon { width: 52px; height: 52px; border-radius: 12px; display: flex; align-items: center; justify-content: center; flex-shrink: 0; }
.stat-info { display: flex; flex-direction: column; }
.stat-info .value { font-size: 26px; font-weight: 700; color: #303133; line-height: 1.2; }
.stat-info .label { font-size: 13px; color: #909399; margin-top: 2px; }
.up { color: #f56c6c; }
.down { color: #67c23a; }
:deep(.high-score-row) { background-color: #fdf6ec !important; }
:deep(.el-table .high-score-row:hover > td) { background-color: #faecd8 !important; }
:deep(.el-tabs__item) { font-size: 14px; font-weight: 500; }
</style>