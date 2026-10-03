import axios from 'axios'
import {createApp} from 'vue'
import {createPinia} from 'pinia'
import App from './App.vue'
import {initializeAxios} from '@/lib/axios-utils'
import vuetify from '@/plugins/vuetify'
import router from '@/router'
import {useContextStore} from '@/stores/context'

initializeAxios(axios)

const app = createApp(App)
  .use(createPinia())
  .use(vuetify)

// Which environment this is and who is signed in, before the first page: the routes depend on both.
useContextStore().init().then(() => {
  app.use(router).mount('#app')
})
