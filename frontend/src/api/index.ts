import { get, post, put } from './client'
import type {
  ListResponse,
  T1Candidate,
  T1Position,
  T1Trade,
  T1StatsResponse,
  T1ScanResponse,
  T1BuyResponse,
  T1SellResponse,
  T1SyncResponse,
  PaginatedResponse,
  LoginResponse,
  UserInfo,
} from '@/types'

export const stockApi = {
  list: (keyword = '', limit = 50) => get('/stocks/list', { keyword, limit }),
  daily: (code: string, start_date = '', end_date = '') =>
    get(`/stocks/${code}/daily`, { start_date, end_date }),
}

export const analysisApi = {
  analyze: (stock_code: string, stock_name = '') =>
    post('/analysis/analyze', { stock_code, stock_name }),
  report: (taskId: string) => get(`/analysis/report/${taskId}`),
  tasks: () => get('/analysis/tasks'),
}

export const recommendApi = {
  today: (top_n = 10) => get('/recommend/today', { top_n }),
  history: (date = '') => get('/recommend/history', { date }),
}

export const backtestApi = {
  run: (data: Record<string, unknown>) => post('/backtest/run', data),
  strategies: () => get('/backtest/strategies'),
}

export const paperApi = {
  account: () => get('/paper/account'),
  order: (data: { ts_code: string; stock_name?: string; direction: string; quantity: number }) =>
    post('/paper/order', data),
  positions: () => get('/paper/positions'),
  orders: (limit = 50) => get('/paper/orders', { limit }),
  reset: () => post('/paper/reset'),
}

export const emotionApi = {
  today: () => get('/emotion/today'),
}

export const strategyApi = {
  healthList: () => get('/strategy/list'),
  health: (name: string) => get(`/strategy/${name}`),
}

export const authApi = {
  login: (username: string, password: string) =>
    post<LoginResponse>('/auth/login', { username, password }),
  register: (username: string, password: string) =>
    post<LoginResponse>('/auth/register', { username, password }),
  me: () => get<UserInfo>('/auth/me'),
}

export const configApi = {
  list: (category = '') => get('/config/list', { category }),
  getKey: (key: string) => get(`/config/${key}`),
  setKey: (key: string, value: string) =>
    put(`/config/${key}`, { value }),
  categories: () => get('/config/categories/list'),
}

export const schedulerApi = {
  tasks: () => get('/scheduler/tasks'),
  trigger: (taskId: string) => post(`/scheduler/trigger/${taskId}`),
  logs: (limit = 20) => get('/scheduler/logs', { limit }),
}

export const t1Api = {
  candidates: (scan_date = '', criterion = '') =>
    get<ListResponse<T1Candidate>>('/t1/candidates', { scan_date, criterion }),
  scan: (scan_date = '') =>
    post<T1ScanResponse>(scan_date ? `/t1/scan?scan_date=${scan_date}` : '/t1/scan'),
  buy: (candidate_id: number, quantity = 100) =>
    post<T1BuyResponse>('/t1/buy', { candidate_id, quantity }),
  sell: (positionId: number, sell_price: number, sell_reason = 'manual') =>
    post<T1SellResponse>(`/t1/sell/${positionId}?sell_price=${sell_price}&sell_reason=${sell_reason}`),
  positions: (status = 'holding') =>
    get<ListResponse<T1Position>>('/t1/positions', { status }),
  trades: (page = 1, page_size = 20, criterion = '') =>
    get<PaginatedResponse<T1Trade>>('/t1/trades', { page, page_size, criterion }),
  stats: () => get<T1StatsResponse>('/t1/stats'),
  backtest: (data: Record<string, unknown>) => post('/t1/backtest', data),
  syncData: (top_n = 50, days = 30) =>
    post<T1SyncResponse>(`/t1/sync-data?top_n=${top_n}&days=${days}`),
}
