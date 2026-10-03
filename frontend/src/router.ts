const BaseView = () => import('@/views/BaseView.vue')
const Drafts = () => import('@/views/Drafts.vue')
const EditJob = () => import('@/views/EditJob.vue')
const Finished = () => import('@/views/Finished.vue')
const Login = () => import('@/views/Login.vue')
const NotFound = () => import('@/views/NotFound.vue')
const Queue = () => import('@/views/Queue.vue')
import type {RouteRecordRaw} from 'vue-router'
import {createRouter, createWebHistory} from 'vue-router'
import {redirectAfterLogin, requiresAuthenticated} from '@/auth'
import {useContextStore} from '@/stores/context'

const routes: RouteRecordRaw[] = [
  {
    path: '/',
    redirect: '/job'
  },
  {
    path: '/login',
    component: Login,
    name: 'Sign in',
    beforeEnter: (to, from, next) => {
      if (useContextStore().currentUser) {
        next(redirectAfterLogin(to.query.redirect))
      } else {
        next()
      }
    }
  },
  {
    path: '/',
    component: BaseView,
    beforeEnter: requiresAuthenticated,
    children: [
      {
        path: '/job',
        component: EditJob,
        name: 'Create / edit job'
      },
      {
        path: '/drafts',
        component: Drafts,
        name: 'Drafts'
      },
      {
        path: '/queue',
        component: Queue,
        name: 'Job queue'
      },
      {
        path: '/finished',
        component: Finished,
        name: 'Finished jobs'
      },
      {
        path: '/404',
        component: NotFound,
        name: 'Page not found'
      },
      {
        path: '/:pathMatch(.*)*',
        redirect: '/404'
      }
    ]
  }
]

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes
})

export default router
