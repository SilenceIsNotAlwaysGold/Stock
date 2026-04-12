import axios from 'axios'
import { ElMessage } from 'element-plus'

const api = axios.create({
  baseURL: '/api',
  timeout: 120000,  // 120 秒，支持 sync-data 等长时间操作
})

// 是否正在刷新 token
let isRefreshing = false
// 等待刷新完成的请求队列
let pendingRequests: Array<(token: string) => void> = []

function onTokenRefreshed(token: string) {
  pendingRequests.forEach((cb) => cb(token))
  pendingRequests = []
}

// 请求拦截器：自动附加 JWT token
api.interceptors.request.use((config) => {
  const token = localStorage.getItem('token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// 响应拦截器：统一错误处理 + 401 自动刷新
api.interceptors.response.use(
  (res) => res.data,
  async (err) => {
    const originalRequest = err.config
    const status = err.response?.status

    // 401: 尝试刷新 token
    if (status === 401 && !originalRequest._retry) {
      // 登录/注册/刷新接口本身 401 直接跳登录
      const authPaths = ['/auth/login', '/auth/register', '/auth/refresh']
      if (authPaths.some((p) => originalRequest.url?.includes(p))) {
        redirectToLogin()
        return Promise.reject(err)
      }

      if (isRefreshing) {
        // 已经在刷新，排队等待
        return new Promise((resolve) => {
          pendingRequests.push((token: string) => {
            originalRequest.headers.Authorization = `Bearer ${token}`
            originalRequest._retry = true
            resolve(api(originalRequest))
          })
        })
      }

      originalRequest._retry = true
      isRefreshing = true

      try {
        const token = localStorage.getItem('token')
        const res = await axios.post('/api/auth/refresh', null, {
          headers: { Authorization: `Bearer ${token}` },
        })
        const newToken = res.data.token
        localStorage.setItem('token', newToken)
        onTokenRefreshed(newToken)
        originalRequest.headers.Authorization = `Bearer ${newToken}`
        return api(originalRequest)
      } catch {
        redirectToLogin()
        return Promise.reject(err)
      } finally {
        isRefreshing = false
      }
    }

    // 提取错误信息
    const msg = extractErrorMessage(err)
    if (status !== 401) {
      ElMessage.error(msg)
    }

    return Promise.reject(err)
  }
)

function extractErrorMessage(err: any): string {
  const data = err.response?.data
  if (data?.error?.message) return data.error.message
  if (data?.detail) {
    if (typeof data.detail === 'string') return data.detail
    if (Array.isArray(data.detail)) return data.detail[0]?.msg || '请求参数错误'
  }
  if (data?.message) return data.message
  if (err.code === 'ECONNABORTED') return '请求超时'
  if (!err.response) return '网络连接失败'
  return `请求失败 (${err.response?.status || 'unknown'})`
}

function redirectToLogin() {
  localStorage.removeItem('token')
  localStorage.removeItem('username')
  const currentPath = window.location.pathname
  if (currentPath !== '/login') {
    ElMessage.warning('登录已过期，请重新登录')
    window.location.href = '/login'
  }
}

// 类型辅助：interceptor 返回 data 而非 AxiosResponse
export function get<T = any>(url: string, params?: any): Promise<T> {
  return api.get(url, { params }) as any
}

export function post<T = any>(url: string, data?: any): Promise<T> {
  return api.post(url, data) as any
}

export function put<T = any>(url: string, data?: any): Promise<T> {
  return api.put(url, data) as any
}

export default api
