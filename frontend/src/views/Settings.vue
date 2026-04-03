<template>
  <div>
    <el-card>
      <template #header>系统配置</template>
      <el-table :data="configs" stripe>
        <el-table-column prop="key" label="配置项" width="200" />
        <el-table-column prop="description" label="描述" />
        <el-table-column prop="category" label="分类" width="120" />
        <el-table-column prop="value" label="值" width="200">
          <template #default="{ row }">
            <span v-if="editingKey !== row.key">{{ row.value }}</span>
            <el-input v-else v-model="editValue" size="small" />
          </template>
        </el-table-column>
        <el-table-column label="操作" width="120">
          <template #default="{ row }">
            <el-button v-if="editingKey !== row.key" size="small" @click="startEdit(row)">编辑</el-button>
            <template v-else>
              <el-button size="small" type="primary" @click="saveEdit(row.key)">保存</el-button>
              <el-button size="small" @click="editingKey = ''">取消</el-button>
            </template>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-card style="margin-top: 20px">
      <template #header>定时任务</template>
      <el-table :data="tasks" stripe>
        <el-table-column prop="name" label="任务" width="140" />
        <el-table-column prop="cron" label="Cron" width="160" />
        <el-table-column prop="description" label="描述" />
        <el-table-column prop="last_status" label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="row.last_status === 'completed' ? 'success' : row.last_status === 'failed' ? 'danger' : 'info'" size="small">
              {{ row.last_status }}
            </el-tag>
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
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { get, post } from '@/api/client'

const configs = ref<any[]>([])
const tasks = ref<any[]>([])
const editingKey = ref('')
const editValue = ref('')

function startEdit(row: any) {
  editingKey.value = row.key
  editValue.value = row.value === '***' ? '' : row.value
}

async function saveEdit(key: string) {
  try {
    await post(`/config/${key}`, { value: editValue.value })  // PUT mapped to post for simplicity
    ElMessage.success('配置已更新')
    editingKey.value = ''
    await loadConfigs()
  } catch {
    ElMessage.error('更新失败')
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
