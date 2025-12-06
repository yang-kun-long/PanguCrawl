import { createRouter, createWebHistory } from 'vue-router'
// 1. 引入您刚才创建的页面组件
import HomeView from '../views/HomeView.vue'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    {
      // 2. 定义首页路由：当访问根路径 / 时，显示 HomeView
      path: '/',
      name: 'home',
      component: HomeView
    }
  ],
})

export default router
