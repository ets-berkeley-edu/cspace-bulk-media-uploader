import type {RouteRecordRaw} from 'vue-router'
import {createRouter, createWebHistory} from 'vue-router'
import Home from '@/views/Home.vue'

// One route for now: Home is the whole app (sign-in, and the four tabs). Sign-in and each tab become routes of their
// own as they are converted to Vuetify.
const routes: RouteRecordRaw[] = [
  {
    path: '/',
    component: Home,
    name: 'Home'
  },
  {
    path: '/:pathMatch(.*)*',
    redirect: '/'
  }
]

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes
})

export default router
