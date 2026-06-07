<template>
  <el-container class="layout">
    <el-aside :width="collapsed ? '64px' : '210px'" class="sidebar">
      <div class="logo">
        <span class="logo-mark">Q8</span>
        <span v-if="!collapsed" class="logo-text">量化交易终端</span>
      </div>
      <el-menu
        :default-active="route.path"
        :collapse="collapsed"
        router
        class="nav-menu"
      >
        <el-menu-item index="/">
          <el-icon><DataAnalysis /></el-icon>
          <template #title>仪表盘</template>
        </el-menu-item>
        <el-menu-item index="/analysis">
          <el-icon><Search /></el-icon>
          <template #title>智能分析</template>
        </el-menu-item>
        <el-menu-item index="/recommend">
          <el-icon><Star /></el-icon>
          <template #title>每日推荐</template>
        </el-menu-item>
        <el-menu-item index="/backtest">
          <el-icon><TrendCharts /></el-icon>
          <template #title>策略回测</template>
        </el-menu-item>
        <el-menu-item index="/strategy">
          <el-icon><Setting /></el-icon>
          <template #title>策略管理</template>
        </el-menu-item>
        <el-menu-item index="/paper">
          <el-icon><Wallet /></el-icon>
          <template #title>模拟盘</template>
        </el-menu-item>
        <el-menu-item index="/sector">
          <el-icon><Histogram /></el-icon>
          <template #title>板块推荐</template>
        </el-menu-item>
        <el-menu-item index="/news-reco">
          <el-icon><Promotion /></el-icon>
          <template #title>消息面推荐</template>
        </el-menu-item>
        <el-menu-item index="/cycle">
          <el-icon><Odometer /></el-icon>
          <template #title>情绪周期</template>
        </el-menu-item>
        <el-menu-item index="/styles">
          <el-icon><Operation /></el-icon>
          <template #title>多风格回测</template>
        </el-menu-item>
        <el-menu-item index="/t1">
          <el-icon><Timer /></el-icon>
          <template #title>T+1隔夜</template>
        </el-menu-item>
        <el-menu-item index="/settings">
          <el-icon><Setting /></el-icon>
          <template #title>系统设置</template>
        </el-menu-item>
      </el-menu>
    </el-aside>
    <el-container>
      <el-header class="header">
        <el-icon class="toggle" @click="collapsed = !collapsed">
          <Fold v-if="!collapsed" />
          <Expand v-else />
        </el-icon>
        <span class="title">A 股智能量化选股平台</span>
        <div class="header-right">
          <span class="market-chip">
            <span class="dot"></span>
            <span class="num">{{ clock }}</span>
          </span>
          <el-button text @click="logout">退出登录</el-button>
        </div>
      </el-header>
      <el-main class="main">
        <router-view />
      </el-main>
    </el-container>
  </el-container>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'

const route = useRoute()
const router = useRouter()
const collapsed = ref(false)

const clock = ref('')
let timer: ReturnType<typeof setInterval> | null = null
function tick() {
  const d = new Date()
  const p = (n: number) => String(n).padStart(2, '0')
  clock.value = `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`
}
onMounted(() => { tick(); timer = setInterval(tick, 1000) })
onUnmounted(() => { if (timer) clearInterval(timer) })

function logout() {
  localStorage.removeItem('token')
  router.push('/login')
}
</script>

<style scoped>
.layout {
  height: 100vh;
}
.sidebar {
  background: var(--bg-surface);
  border-right: 1px solid var(--border);
  transition: width 0.25s ease;
  overflow: hidden;
}
.logo {
  height: 60px;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 0 18px;
  border-bottom: 1px solid var(--border);
}
.logo-mark {
  width: 30px;
  height: 30px;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
  font-weight: 800;
  color: #07121f;
  background: linear-gradient(135deg, #4cb0ff, #2bd4c4);
  box-shadow: 0 0 14px rgba(62, 166, 255, 0.45);
  flex-shrink: 0;
}
.logo-text {
  font-size: 16px;
  font-weight: 700;
  color: var(--text-1);
  letter-spacing: 0.5px;
  white-space: nowrap;
}
.nav-menu {
  border-right: none;
  padding: 8px;
}
.nav-menu :deep(.el-menu-item) {
  border-radius: 8px;
  margin: 2px 0;
  height: 44px;
  color: var(--text-2);
}
.header {
  display: flex;
  align-items: center;
  background: var(--bg-elevated);
  border-bottom: 1px solid var(--border);
  padding: 0 20px;
  position: sticky;
  top: 0;
  z-index: 10;
}
.toggle {
  cursor: pointer;
  font-size: 20px;
  margin-right: 16px;
  color: var(--text-2);
}
.toggle:hover {
  color: var(--accent);
}
.title {
  font-size: 16px;
  font-weight: 600;
  color: var(--text-1);
  letter-spacing: 0.3px;
}
.header-right {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 16px;
}
.market-chip {
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 4px 12px;
  border: 1px solid var(--border);
  border-radius: 999px;
  background: var(--bg-inset);
  font-size: 13px;
  color: var(--text-2);
}
.market-chip .dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--down);
  box-shadow: 0 0 8px var(--down);
}
.main {
  background: var(--bg-base);
  padding: 18px;
}
</style>
