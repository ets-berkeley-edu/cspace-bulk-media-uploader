import './main.scss'
import {aliases, mdi} from 'vuetify/iconsets/mdi-svg'
import {createVuetify} from 'vuetify'
import {VApp} from 'vuetify/components/VApp'
import {VBtn} from 'vuetify/components/VBtn'
import {VIcon} from 'vuetify/components/VIcon'
import {VMain} from 'vuetify/components/VMain'

/**
 * Vuetify set up as BOA sets it up: components registered by hand (add each one here when a screen first uses it,
 * so the bundle holds only what the BMU uses), icons from @mdi/js, and BOA's theme colours and control defaults.
 */
export default createVuetify({
  components: {
    VApp,
    VBtn,
    VIcon,
    VMain
  },
  defaults: {
    VBtn: {
      style: 'text-transform: none;'
    },
    VTextField: {
      density: 'compact',
      variant: 'outlined'
    }
  },
  display: {
    thresholds: {
      xs: 0,
      sm: 600,
      md: 960,
      lg: 1400,
      xl: 1920
    }
  },
  icons: {
    defaultSet: 'mdi',
    aliases,
    sets: {
      mdi
    }
  },
  theme: {
    variations: {
      colors: ['primary', 'success'],
      lighten: 0,
      darken: 1
    },
    themes: {
      light: {
        colors: {
          'accent-blue': '#005c91',
          'accent-green': '#36a600',
          'accent-orange': '#e48600',
          'accent-purple': '#b300c5',
          'accent-red': '#d0021b',
          anchor: '#37769a',
          'anchor-hover': '#0056b3',
          body: '#212529',
          error: '#cf1715',
          gold: '#826F03',
          grey: '#757575',
          info: '#367da1',
          'light-blue': '#c0ecff',
          'light-grey': '#f9f9f9',
          'light-yellow': '#ffecc0',
          'pale-blue': '#f3fbff',
          'pale-yellow': '#fef6e6',
          primary: '#37769a',
          quaternary: '#083456',
          secondary: '#96C3de',
          'sky-blue': '#ebf8ff',
          success: '#437f4b',
          'surface-light': '#f5f5f5',
          tertiary: '#125074',
          warning: '#C74600'
        }
      }
    }
  }
})
