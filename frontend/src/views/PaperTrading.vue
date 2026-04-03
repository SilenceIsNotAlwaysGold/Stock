<template>
  <div>
    <el-row :gutter="20">
      <el-col :span="8">
        <el-card>
          <template #header>模拟账户</template>
          <el-descriptions :column="1" size="small">
            <el-descriptions-item label="初始资金">{{ account.initial_cash?.toLocaleString() }}</el-descriptions-item>
            <el-descriptions-item label="可用资金">{{ account.cash?.toLocaleString() }}</el-descriptions-item>
            <el-descriptions-item label="持仓市值">{{ account.total_market_value?.toLocaleString() }}</el-descriptions-item>
            <el-descriptions-item label="总资产">{{ account.total_equity?.toLocaleString() }}</el-descriptions-item>
            <el-descriptions-item label="总盈亏">
              <span :style="{ color: (account.total_pnl ?? 0) >= 0 ? '#67c23a' : '#f56c6c' }">
                {{ account.total_pnl?.toFixed(2) }}
              </span>
            </el-descriptions-item>
          </el-descriptions>
          <el-button size="small" type="danger" @click="resetAccount" style="margin-top: 12px">重置账户</el-button>
        </el-card>
      </el-col>
      <el-col :span="16">
        <el-card>
          <template #header>下单</template>
          <el-form inline>
            <el-form-item label="代码">
              <el-input v-model="order.ts_code" placeholder="000001.SZ" style="width: 140px" />
            </el-form-item>
            <el-form-item label="方向">
              <el-select v-model="order.direction" style="width: 100px">
                <el-option label="买入" value="BUY" />
                <el-option label="卖出" value="SELL" />
              </el-select>
            </el-form-item>
            <el-form-item label="数量">
              <el-input-number v-model="order.quantity" :min="100" :step="100" style="width: 120px" />
            </el-form-item>
            <el-form-item label="价格">
              <el-input-number v-model="order.price" :min="0.01" :precision="2" style="width: 120px" />
            </el-form-item>
            <el-form-item>
              <el-button :type="order.direction === 'BUY' ? 'success' : 'danger'" @click="placeOrder">
                {{ order.direction === 'BUY' ? '买入' : '卖出' }}
              </el-button>
            </el-form-item>
          </el-form>
        </el-card>
      </el-col>
    </el-row>

    <el-row :gutter="20" style="margin-top: 20px">
      <el-col :span="12">
        <el-card>
          <template #header>持仓</template>
          <el-table :data="positions" size="small" stripe>
            <el-table-column prop="ts_code" label="代码" width="100" />
            <el-table-column prop="quantity" label="数量" width="80" />
            <el-table-column prop="avg_cost" label="成本" width="80" />
            <el-table-column prop="market_value" label="市值" width="100" />
            <el-table-column prop="unrealized_pnl" label="盈亏" width="100">
              <template #default="{ row }">
                <span :style="{ color: row.unrealized_pnl >= 0 ? '#67c23a' : '#f56c6c' }">
                  {{ row.unrealized_pnl }}
                </span>
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-col>
      <el-col :span="12">
        <el-card>
          <template #header>交易记录</template>
          <el-table :data="orders" size="small" stripe>
            <el-table-column prop="ts_code" label="代码" width="100" />
            <el-table-column prop="direction" label="方向" width="60">
              <template #default="{ row }">
                <el-tag :type="row.direction === 'BUY' ? 'success' : 'danger'" size="small">
                  {{ row.direction === 'BUY' ? '买' : '卖' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="quantity" label="数量" width="80" />
            <el-table-column prop="price" label="价格" width="80" />
            <el-table-column prop="fee" label="手续费" width="80" />
          </el-table>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { paperApi } from '@/api'

const account = ref<any>({})
const positions = ref<any[]>([])
const orders = ref<any[]>([])
const order = ref({ ts_code: '000001.SZ', direction: 'BUY', quantity: 100, price: 10.0 })

async function loadData() {
  try { account.value = await paperApi.account() } catch {}
  try { positions.value = await paperApi.positions() as any } catch {}
  try { orders.value = await paperApi.orders() as any } catch {}
}

async function placeOrder() {
  try {
    await paperApi.order(order.value)
    ElMessage.success('下单成功')
    await loadData()
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '下单失败')
  }
}

async function resetAccount() {
  await paperApi.reset()
  ElMessage.success('账户已重置')
  await loadData()
}

onMounted(loadData)
</script>
