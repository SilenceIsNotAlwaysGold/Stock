<template>
  <div class="login-container">
    <div class="login-card glass">
      <div class="brand">
        <span class="brand-mark">Q8</span>
        <h2 class="brand-title">量化交易终端 <span class="ver">v8</span></h2>
        <p class="brand-sub">A 股智能量化选股 · 暗色终端</p>
      </div>
      <el-form :model="form">
        <el-form-item>
          <el-input v-model="form.username" placeholder="请输入用户名" prefix-icon="User" size="large" />
        </el-form-item>
        <el-form-item>
          <el-input v-model="form.password" type="password" placeholder="请输入密码" prefix-icon="Lock" show-password size="large" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" size="large" style="width: 100%" @click="handleLogin" :loading="loading">
            登录
          </el-button>
        </el-form-item>
        <el-form-item>
          <el-button size="large" style="width: 100%" @click="handleRegister" :loading="loading">
            注册
          </el-button>
        </el-form-item>
      </el-form>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { authApi } from '@/api'

const router = useRouter()
const form = ref({ username: '', password: '' })
const loading = ref(false)

async function handleLogin() {
  if (!form.value.username || !form.value.password) {
    ElMessage.warning('请输入用户名和密码')
    return
  }
  loading.value = true
  try {
    const res = await authApi.login(form.value.username, form.value.password)
    localStorage.setItem('token', res.token)
    localStorage.setItem('username', res.username)
    ElMessage.success('登录成功')
    router.push('/')
  } catch (err: any) {
    const msg = err.response?.data?.detail || '用户名或密码错误'
    ElMessage.error(msg)
  } finally {
    loading.value = false
  }
}

async function handleRegister() {
  loading.value = true
  try {
    const res = await authApi.register(form.value.username, form.value.password)
    localStorage.setItem('token', res.token)
    localStorage.setItem('username', res.username)
    ElMessage.success('注册成功')
    router.push('/')
  } catch {
    // client.ts 已统一提示
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-container {
  display: flex;
  justify-content: center;
  align-items: center;
  height: 100vh;
  background-color: var(--bg-base);
  background-image:
    radial-gradient(800px 600px at 50% 12%, rgba(62, 166, 255, 0.14), transparent 60%),
    radial-gradient(600px 500px at 80% 100%, rgba(43, 212, 196, 0.08), transparent 55%),
    linear-gradient(rgba(255, 255, 255, 0.02) 1px, transparent 1px),
    linear-gradient(90deg, rgba(255, 255, 255, 0.02) 1px, transparent 1px);
  background-size: 100% 100%, 100% 100%, 40px 40px, 40px 40px;
}
.login-card {
  width: 400px;
  padding: 36px 34px;
  box-shadow: 0 24px 60px rgba(0, 0, 0, 0.5);
}
.brand {
  text-align: center;
  margin-bottom: 28px;
}
.brand-mark {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 48px;
  height: 48px;
  border-radius: 12px;
  font-size: 20px;
  font-weight: 800;
  color: #07121f;
  background: linear-gradient(135deg, #4cb0ff, #2bd4c4);
  box-shadow: 0 0 22px rgba(62, 166, 255, 0.5);
  margin-bottom: 14px;
}
.brand-title {
  margin: 0 0 6px;
  font-size: 22px;
  font-weight: 700;
  color: var(--text-1);
  letter-spacing: 0.5px;
}
.brand-title .ver {
  color: var(--accent);
}
.brand-sub {
  margin: 0;
  font-size: 12px;
  color: var(--text-3);
  letter-spacing: 1px;
}
</style>
