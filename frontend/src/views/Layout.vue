<template>
  <el-container class="layout">
    <el-aside :width="collapsed ? '64px' : '200px'" class="sidebar">
      <div class="logo">
        <span v-if="!collapsed">量化选股 v8</span>
        <span v-else>Q8</span>
      </div>
      <el-menu
        :default-active="route.path"
        :collapse="collapsed"
        router
        background-color="#1d1e1f"
        text-color="#bfcbd9"
        active-text-color="#409eff"
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
        <div style="margin-left: auto">
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
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

const route = useRoute()
const router = useRouter()
const collapsed = ref(false)

function logout() {
  localStorage.removeItem('token')
  router.push('/login')
}
</script>

<style scoped>
.layout { height: 100vh; }
.sidebar { background: #1d1e1f; transition: width 0.3s; overflow: hidden; }
.logo { height: 60px; display: flex; align-items: center; justify-content: center; color: #409eff; font-size: 18px; font-weight: bold; }
.header { display: flex; align-items: center; background: #fff; border-bottom: 1px solid #e6e6e6; padding: 0 20px; }
.toggle { cursor: pointer; font-size: 20px; margin-right: 16px; }
.title { font-size: 16px; font-weight: 500; }
.main { background: #f5f7fa; }
</style>
