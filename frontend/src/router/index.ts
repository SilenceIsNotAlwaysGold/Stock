import { createRouter, createWebHistory } from 'vue-router'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/login',
      name: 'Login',
      component: () => import('@/views/Login.vue'),
      meta: { public: true },
    },
    {
      path: '/',
      component: () => import('@/views/Layout.vue'),
      children: [
        { path: '', name: 'Dashboard', component: () => import('@/views/Dashboard.vue') },
        { path: 'analysis', name: 'Analysis', component: () => import('@/views/Analysis.vue') },
        { path: 'recommend', name: 'Recommend', component: () => import('@/views/Recommend.vue') },
        { path: 'backtest', name: 'Backtest', component: () => import('@/views/Backtest.vue') },
        { path: 'paper', name: 'PaperTrading', component: () => import('@/views/PaperTrading.vue') },
        { path: 'sector', name: 'SectorRecommend', component: () => import('@/views/SectorRecommend.vue') },
        { path: 'news-reco', name: 'NewsReco', component: () => import('@/views/NewsReco.vue') },
        { path: 'cycle', name: 'MarketCycle', component: () => import('@/views/MarketCycle.vue') },
        { path: 'styles', name: 'StyleBacktest', component: () => import('@/views/StyleBacktest.vue') },
        { path: 't1', name: 'T1Strategy', component: () => import('@/views/T1Strategy.vue') },
        { path: 'strategy', name: 'Strategy', component: () => import('@/views/Strategy.vue') },
        { path: 'settings', name: 'Settings', component: () => import('@/views/Settings.vue') },
      ],
    },
  ],
})

// 路由守卫：未登录跳转到登录页
router.beforeEach((to, _from, next) => {
  const token = localStorage.getItem('token')
  if (!to.meta.public && !token) {
    next({ name: 'Login' })
  } else {
    next()
  }
})

export default router
