import axios from 'axios'
import {createApp} from 'vue'
import {createPinia} from 'pinia'
import App from './App.vue'
import {initializeAxios} from '@/lib/axios-utils'
import vuetify from '@/plugins/vuetify'
import router from '@/router'
// After Vuetify's styles, so the screens not yet converted keep their own look. Goes away with the last of them.
import './style.css'

initializeAxios(axios)

createApp(App)
  .use(createPinia())
  .use(vuetify)
  .use(router)
  .mount('#app')
