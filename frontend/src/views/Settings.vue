<template>
  <div>
    <el-card>
      <template #header>
        <div style="display:flex; justify-content:space-between; align-items:center">
          <span>系统配置</span>
          <el-select v-model="filterCategory" placeholder="全部分类" clearable size="small" style="width:160px">
            <el-option label="全部" value="" />
            <el-option label="数据源" value="data_source" />
            <el-option label="LLM" value="llm" />
            <el-option label="T1 策略" value="t1_strategy" />
            <el-option label="T1 卖出" value="t1_sell" />
            <el-option label="T1 仓位" value="t1_position" />
            <el-option label="通知" value="notification" />
          </el-select>
        </div>
      </template>

      <el-table :data="filteredConfigs" stripe size="small">
        <el-table-column prop="key" label="配置项" width="220" />
        <el-table-column prop="description" label="说明" min-width="200" />
        <el-table-column prop="category" label="分类" width="100">
          <template #default="{ row }">
            <el-tag size="small" :type="categoryTagType(row.category)">{{ categoryLabel(row.category) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="当前值" width="180">
          <template #default="{ row }">
            <span v-if="editingKey !== row.key" style="font-family:monospace">{{ row.value }}</span>
            <el-input
              v-else
              v-model="editValue"
              size="small"
              :type="row.sensitive ? 'password' : 'text'"
              :placeholder="row.sensitive ? '输入新值（留空则不更改）' : ''"
              show-password
            />
          </template>
        </el-table-column>
        <el-table-column label="操作" width="130">
          <template #default="{ row }">
            <el-button v-if="editingKey !== row.key" size="small" @click="startEdit(row)">编辑</el-button>
            <template v-else>
              <el-button size="small" type="primary" @click="saveEdit(row.key)" :loading="saving">保存</el-button>
              <el-button size="small" @click="cancelEdit">取消</el-button>
            </template>
          </template>
        </el-table-column>
      </el-table>

      <el-alert
        type="warning"
        :closable="false"
        style="margin-top:12px"
        title="配置保存后立即生效，但重启服务后会恢复为 .env 文件中的值。如需永久生效请同时修改 .env 文件。"
      />
    </el-card>

    <el-card style="margin-top: 20px">
      <template #header>定时任务</template>
      <el-table :data="tasks" stripe size="small">
        <el-table-column prop="name" label="任务" width="140" />
        <el-table-column prop="cron" label="Cron" width="160" />
        <el-table-column prop="description" label="描述" />
        <el-table-column prop="last_status" label="状态" width="100">
          <template #default="{ row }">
            <el-tag
              :type="row.last_status === 'completed' ? 'success' : row.last_status === 'failed' ? 'danger' : 'info'"
              size="small"
            >{{ row.last_status }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="100">
          <template #default="{ row }">
            <el-button size="small" type="warning" @click="triggerTask(row.id)">触发</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { get, post, put } from '@/api/client'

const configs = ref<any[]>([])
const tasks = ref<any[]>([])
const editingKey = ref('')
const editValue = ref('')
const saving = ref(false)
const filterCategory = ref('')

const filteredConfigs = computed(() =>
  filterCategory.value
    ? configs.value.filter(c => c.category === filterCategory.value)
    : configs.value
)

const categoryLabel = (c: string) => ({
  data_source: '数据源', llm: 'LLM',
  t1_strategy: 'T1策略', t1_sell: 'T1卖出', t1_position: 'T1仓位',
  notification: '通知',
}[c] ?? c)

const categoryTagType = (c: string) => ({
  data_source: 'info', llm: 'warning',
  t1_strategy: 'success', t1_sell: 'danger', t1_position: '',
  notification: 'warning',
}[c] ?? 'info')

function startEdit(row: any) {
  editingKey.value = row.key
  editValue.value = row.sensitive ? '' : row.value
}

function cancelEdit() {
  editingKey.value = ''
  editValue.value = ''
}

async function saveEdit(key: string) {
  saving.value = true
  try {
    const res: any = await put(`/config/${key}`, { value: editValue.value })
    if (res.status === 'skipped') {
      ElMessage.info('敏感字段未变更（留空则保持原值）')
    } else {
      ElMessage.success('配置已更新并立即生效')
    }
    cancelEdit()
    await loadConfigs()
  } catch {
    ElMessage.error('更新失败，请检查输入格式')
  } finally {
    saving.value = false
  }
}

async function triggerTask(taskId: string) {
  try {
    await post(`/scheduler/trigger/${taskId}`)
    ElMessage.success('任务已触发')
    await loadTasks()
  } catch {
    ElMessage.error('触发失败')
  }
}

async function loadConfigs() {
  try { configs.value = await get('/config/list') } catch {}
}

async function loadTasks() {
  try {
    const res: any = await get('/scheduler/tasks')
    tasks.value = res.tasks ?? []
  } catch {}
}

onMounted(() => {
  loadConfigs()
  loadTasks()
})
</script>
