<template>
  <div class="analysis">
    <!-- 输入栏 -->
    <el-card class="glass toolbar">
      <div class="bar">
        <el-input v-model="stockCode" placeholder="股票代码，如 000001.SZ"
                  style="width: 240px" @keyup.enter="runAI" clearable />
        <el-button type="primary" :loading="aiLoading" @click="runAI">
          <el-icon><MagicStick /></el-icon>&nbsp;AI 决策分析
        </el-button>
        <el-switch v-model="useLlm" active-text="LLM 叙事" inline-prompt />
        <span class="hint">量化(技术/资金/趋势) + 真实消息面，LLM 不可用自动规则兜底</span>
      </div>
    </el-card>

    <el-card v-if="aiLoading" class="glass" style="margin-top:14px">
      <div class="stage">
        <el-icon class="rot"><Loading /></el-icon>
        <span class="stage-txt">{{ stageText }}</span>
        <span class="stage-el">已用 {{ elapsed }}s</span>
      </div>
      <el-progress :percentage="stagePct" :show-text="false" :stroke-width="6"
                   color="#3ea6ff" style="margin-top:10px" />
    </el-card>

    <el-alert v-if="aiError" :title="aiError" type="warning" show-icon
              style="margin-top:14px" :closable="false" />

    <!-- AI 决策卡 -->
    <div v-if="ai" class="ai-grid">
      <!-- 评分总览 -->
      <el-card class="glass score-card">
        <div class="score-ring">
          <el-progress type="dashboard" :percentage="ai.score" :width="150"
                       :color="scoreColor" :stroke-width="10">
            <template #default>
              <div class="ring-in">
                <div class="ring-num num">{{ ai.score }}</div>
                <div class="ring-lbl">综合评分</div>
              </div>
            </template>
          </el-progress>
        </div>
        <div class="rating">
          <el-tag :type="ratingType" effect="dark" size="large">{{ ai.rating }}</el-tag>
          <span class="stock-name">{{ ai.name }} <small>{{ ai.ts_code }}</small></span>
        </div>
        <div class="zones">
          <div class="z"><span>现价</span><b class="num">{{ ai.price_zones.current }}</b></div>
          <div class="z"><span>买入区</span><b class="num up">{{ ai.price_zones.buy_zone[0] }} ~ {{ ai.price_zones.buy_zone[1] }}</b></div>
          <div class="z"><span>止损</span><b class="num down">{{ ai.price_zones.stop_loss }}</b></div>
          <div class="z"><span>目标</span><b class="num up">{{ ai.price_zones.target }}</b></div>
        </div>
      </el-card>

      <!-- 分项 + 叙事 -->
      <el-card class="glass detail-card">
        <div class="breakdown">
          <div v-for="(v, k) in ai.breakdown" :key="k" class="bd-row">
            <span class="bd-k">{{ bdLabel[String(k)] }}</span>
            <el-progress :percentage="Math.round(Number(v) / ai.breakdown_max[String(k)] * 100)"
                         :color="barColor(String(k))" :show-text="false" :stroke-width="10"
                         style="flex:1;margin:0 12px" />
            <span class="bd-v num">{{ v }} / {{ ai.breakdown_max[String(k)] }}</span>
          </div>
        </div>
        <div class="narrative">
          <div class="nv-head">
            <el-icon><ChatLineSquare /></el-icon> AI 点评
            <el-tag size="small" :type="ai.llm_used ? 'success' : 'info'" effect="plain">
              {{ ai.llm_used ? 'LLM' : '规则引擎' }}
            </el-tag>
            <el-tag size="small" effect="plain"
                    :type="ai.news_polarity === '偏多' ? 'danger' : ai.news_polarity === '偏空' ? 'success' : 'info'">
              消息面{{ ai.news_polarity }}
            </el-tag>
          </div>
          <p>{{ ai.narrative }}</p>
        </div>
        <el-row :gutter="14">
          <el-col :span="12">
            <div class="list-h up-c">🚀 催化剂</div>
            <ul class="mini"><li v-for="(c,i) in ai.catalysts" :key="i">{{ c }}</li>
              <li v-if="!ai.catalysts.length" class="muted">暂无明确催化</li></ul>
          </el-col>
          <el-col :span="12">
            <div class="list-h down-c">⚠️ 风险</div>
            <ul class="mini"><li v-for="(r,i) in ai.risks" :key="i">{{ r }}</li></ul>
          </el-col>
        </el-row>
      </el-card>

      <!-- 相关新闻 -->
      <el-card class="glass news-card">
        <template #header><span>相关消息面（{{ ai.news.length }}）</span></template>
        <div v-for="(n,i) in ai.news" :key="i" class="news-item">
          <div class="nt">{{ n.title }}</div>
          <div class="nm">{{ n.pub_time }}</div>
          <div class="nc" v-if="n.content">{{ n.content }}</div>
        </div>
        <el-empty v-if="!ai.news.length" description="近期无个股新闻" :image-size="60" />
      </el-card>
    </div>

    <!-- 多 Agent 深度分析（保留） -->
    <el-card class="glass" style="margin-top: 16px">
      <template #header>
        <span>多 Agent 深度分析（耗时较长，可选）</span>
      </template>
      <el-button @click="startAnalysis" :loading="analyzing" size="small">
        启动多 Agent 协作分析
      </el-button>
      <div v-if="analyzing" style="margin-top: 16px">
        <el-progress :percentage="progress" :status="progressStatus" />
        <p class="muted" style="margin-top: 8px">{{ currentNode }}</p>
      </div>
      <el-tabs v-if="report" style="margin-top:16px">
        <el-tab-pane label="技术面"><pre class="report-text">{{ report.analysts?.market }}</pre></el-tab-pane>
        <el-tab-pane label="基本面"><pre class="report-text">{{ report.analysts?.fundamental }}</pre></el-tab-pane>
        <el-tab-pane label="新闻面"><pre class="report-text">{{ report.analysts?.news }}</pre></el-tab-pane>
        <el-tab-pane label="多空辩论">
          <pre class="report-text">{{ report.debate?.bull }}

{{ report.debate?.bear }}

{{ report.debate?.conclusion }}</pre>
        </el-tab-pane>
      </el-tabs>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { ElMessage } from 'element-plus'
import { analysisApi } from '@/api'
import { get } from '@/api/client'

const stockCode = ref('000001.SZ')
const useLlm = ref(true)
const aiLoading = ref(false)
const aiError = ref('')
const ai = ref<any>(null)

const bdLabel: Record<string, string> = {
  technical: '技术面', capital: '资金面', news: '消息面', trend: '趋势结构',
}

const scoreColor = computed(() => {
  const s = ai.value?.score ?? 0
  if (s >= 78) return '#ff5c5c'
  if (s >= 62) return '#f0b429'
  if (s >= 45) return '#3ea6ff'
  return '#26d07c'
})
const ratingType = computed(() => {
  const r = ai.value?.rating
  if (r === '强烈推荐') return 'danger'
  if (r === '推荐') return 'warning'
  if (r === '中性') return 'info'
  return 'success'
})
function barColor(k: string) {
  return { technical: '#3ea6ff', capital: '#2bd4c4', news: '#f0b429', trend: '#a371f7' }[k] || '#3ea6ff'
}

const elapsed = ref(0)
const stageText = ref('')
const stagePct = ref(0)
let stageTimer: any = null

function startStages() {
  elapsed.value = 0
  stagePct.value = 4
  stageText.value = '① 查询行情数据…'
  stageTimer = setInterval(() => {
    elapsed.value = +(elapsed.value + 0.5).toFixed(1)
    const t = elapsed.value
    if (t < 1.5) { stageText.value = '① 查询行情数据…'; stagePct.value = Math.min(20, stagePct.value + 3) }
    else if (t < 3.5) { stageText.value = '② 拉取最新消息面（财经新闻）…'; stagePct.value = Math.min(45, stagePct.value + 3) }
    else { stageText.value = useLlm.value ? '③ AI（LLM）综合研判中…' : '③ 规则引擎研判中…'; stagePct.value = Math.min(92, stagePct.value + 2) }
  }, 500)
}
function stopStages() {
  if (stageTimer) { clearInterval(stageTimer); stageTimer = null }
}

async function runAI() {
  if (!stockCode.value.trim()) { ElMessage.warning('请输入股票代码'); return }
  aiLoading.value = true
  aiError.value = ''
  ai.value = null
  startStages()
  try {
    const r: any = await get(`/analysis/ai/${stockCode.value.trim()}`, { use_llm: useLlm.value })
    if (r.error) { aiError.value = r.error; return }
    ai.value = r
  } catch (e: any) {
    aiError.value = e?.response?.data?.detail || e?.message || 'AI 分析失败'
  } finally {
    stopStages()
    aiLoading.value = false
  }
}

// ── 保留的多 Agent 分析 ──
const analyzing = ref(false)
const progress = ref(0)
const currentNode = ref('')
const report = ref<any>(null)
const progressStatus = computed(() => (progress.value >= 100 ? 'success' : ''))

async function startAnalysis() {
  analyzing.value = true
  progress.value = 0
  report.value = null
  try {
    const res: any = await analysisApi.analyze(stockCode.value)
    const taskId = res.task_id
    let polls = 0
    const MAX_POLLS = 158   // ~316s 客户端兜底，略大于后端 300s 超时
    const poll = setInterval(async () => {
      polls++
      if (polls > MAX_POLLS) {
        clearInterval(poll); analyzing.value = false
        ElMessage.error('多 Agent 分析超时，请改用上方「AI 决策分析」（秒级，含规则兜底）')
        return
      }
      try {
        const task: any = await analysisApi.report(taskId)
        if (task.status === 'completed' || task.analysts) {
          clearInterval(poll); progress.value = 100; report.value = task; analyzing.value = false
          ElMessage.success('多 Agent 分析完成')
        } else if (task.status === 'failed') {
          clearInterval(poll); analyzing.value = false
          ElMessage.error(task.error || '多 Agent 分析失败，请改用上方「AI 决策分析」')
        } else {
          // 后端有真实进度则用之，否则缓慢假进度（封顶 95）
          progress.value = task.progress > 0
            ? Math.max(progress.value, Math.min(task.progress, 95))
            : Math.min(progress.value + 4, 95)
          currentNode.value = task.current_node || `分析中…（${polls * 2}s）`
        }
      } catch (err: any) {
        // 404 = 任务在后端不存在（多为后端重启导致内存任务丢失）→ 立即停止，单次提示
        if (err?.response?.status === 404) {
          clearInterval(poll); analyzing.value = false
          ElMessage.error('分析任务已失效（后端可能已重启），请重新发起')
          return
        }
        progress.value = Math.min(progress.value + 2, 95)
      }
    }, 2000)
  } catch (e: any) {
    analyzing.value = false
    ElMessage.error(e?.response?.data?.error?.message || e?.message || '分析请求失败')
  }
}
</script>

<style scoped>
.bar { display: flex; align-items: center; gap: 14px; flex-wrap: wrap; }
.hint { color: var(--text-3); font-size: 12px; }
.ai-grid { display: grid; grid-template-columns: 320px 1fr 360px; gap: 14px; margin-top: 14px; }
.score-card { display: flex; flex-direction: column; align-items: center; }
.score-ring { padding: 8px 0; }
.ring-in { text-align: center; }
.ring-num { font-size: 34px; font-weight: 800; color: var(--text-1); }
.ring-lbl { font-size: 12px; color: var(--text-3); }
.rating { display: flex; flex-direction: column; align-items: center; gap: 8px; margin: 10px 0 16px; }
.stock-name { font-size: 16px; font-weight: 700; color: var(--text-1); }
.stock-name small { color: var(--text-3); font-weight: 400; }
.zones { width: 100%; }
.z { display: flex; justify-content: space-between; padding: 7px 0; border-bottom: 1px solid var(--border); font-size: 13px; }
.z span { color: var(--text-3); }
.bd-row { display: flex; align-items: center; margin: 12px 0; }
.bd-k { width: 60px; font-size: 13px; color: var(--text-2); }
.bd-v { width: 70px; text-align: right; font-size: 13px; color: var(--text-1); }
.narrative { margin: 18px 0; padding: 14px; background: var(--bg-inset); border-radius: 10px; border: 1px solid var(--border); }
.nv-head { display: flex; align-items: center; gap: 8px; font-size: 13px; color: var(--text-2); margin-bottom: 8px; }
.narrative p { margin: 0; line-height: 1.8; color: var(--text-1); font-size: 14px; }
.list-h { font-size: 13px; font-weight: 600; margin-bottom: 6px; }
.up-c { color: var(--up); }
.down-c { color: var(--down); }
.mini { margin: 0; padding-left: 18px; }
.mini li { font-size: 12px; color: var(--text-2); line-height: 1.7; }
.muted { color: var(--text-3); }
.news-card { max-height: 560px; overflow-y: auto; }
.news-item { padding: 10px 0; border-bottom: 1px solid var(--border); }
.nt { font-size: 13px; color: var(--text-1); line-height: 1.5; }
.nm { font-size: 11px; color: var(--text-3); margin: 4px 0; }
.nc { font-size: 12px; color: var(--text-2); line-height: 1.5; }
.report-text { white-space: pre-wrap; font-size: 13px; line-height: 1.6; background: var(--bg-inset); color: var(--text-2); padding: 12px; border-radius: 8px; max-height: 400px; overflow-y: auto; border: 1px solid var(--border); }
@media (max-width: 1200px) { .ai-grid { grid-template-columns: 1fr; } }
.stage { display: flex; align-items: center; gap: 10px; }
.stage-txt { font-size: 14px; color: var(--text-1); font-weight: 600; }
.stage-el { margin-left: auto; font-size: 12px; color: var(--text-3); }
.rot { animation: spin 1s linear infinite; color: var(--accent); }
@keyframes spin { from { transform: rotate(0); } to { transform: rotate(360deg); } }
</style>
