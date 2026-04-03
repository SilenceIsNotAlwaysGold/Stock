// T+1 策略相关类型
export interface T1Candidate {
  id: number
  scan_date: string
  ts_code: string
  stock_name: string
  criterion: string
  score: number
  close_price: number | null
  change_pct: number | null
  volume_ratio: number | null
  turnover_rate: number | null
  status: string
  reason: string
}

export interface T1Position {
  id: number
  ts_code: string
  stock_name: string
  buy_date: string
  buy_price: number
  quantity: number
  criterion: string
  status: string
}

export interface T1Trade {
  id: number
  ts_code: string
  stock_name: string
  criterion: string
  buy_date: string
  buy_price: number
  sell_date: string
  sell_price: number
  quantity: number
  sell_reason: string
  pnl: number
  pnl_pct: number
  is_win: boolean
}

export interface T1CriteriaStats {
  criterion: string
  period: string
  total_trades: number
  win_count: number
  win_rate: number
  avg_pnl_pct: number
  max_pnl_pct: number | null
  min_pnl_pct: number | null
}

export interface T1Overview {
  candidates_today: number
  positions_holding: number
  total_trades: number
  win_rate: number
  total_pnl: number
}

// API 响应包装类型
export interface ListResponse<T> {
  total: number
  items: T[]
}

export interface T1StatsResponse {
  overview: T1Overview
  criteria: T1CriteriaStats[]
}

export interface T1ScanResponse {
  scan_date: string
  found: number
  candidates: Array<{
    ts_code: string
    stock_name: string
    criterion: string
    score: number
    reason: string
  }>
}

export interface T1BuyResponse {
  success: boolean
  error?: string
  position_id?: number
  ts_code?: string
  stock_name?: string
  buy_price?: number
  quantity?: number
}

export interface T1SellResponse {
  success: boolean
  error?: string
  trade_id?: number
  ts_code?: string
  sell_price?: number
  sell_reason?: string
  pnl?: number
  pnl_pct?: number
  is_win?: boolean
}

export interface T1SyncResponse {
  success: boolean
  error?: string
  stocks_synced: number
  stocks_total: number
  bars_synced: number
  active_codes_count: number
  errors: string[]
}

export interface PaginatedResponse<T> {
  total: number
  page: number
  page_size: number
  items: T[]
}

// 通用类型
export interface LoginResponse {
  token: string
  username: string
  role: string
  expires_in: number
}

export interface UserInfo {
  username: string
  role: string
  created_at: string
}
