import './main.scss'
import {aliases, mdi} from 'vuetify/iconsets/mdi-svg'
import {createVuetify} from 'vuetify'
import {VAlert} from 'vuetify/components/VAlert'
import {VApp} from 'vuetify/components/VApp'
import {VAppBar} from 'vuetify/components/VAppBar'
import {VBtn} from 'vuetify/components/VBtn'
import {VCard, VCardText} from 'vuetify/components/VCard'
import {VChip} from 'vuetify/components/VChip'
import {VDialog} from 'vuetify/components/VDialog'
import {VDivider} from 'vuetify/components/VDivider'
import {VExpansionPanel, VExpansionPanelText, VExpansionPanelTitle, VExpansionPanels} from 'vuetify/components/VExpansionPanel'
import {VForm} from 'vuetify/components/VForm'
import {VIcon} from 'vuetify/components/VIcon'
import {VLazy} from 'vuetify/components/VLazy'
import {VList, VListItem, VListItemTitle} from 'vuetify/components/VList'
import {VMain} from 'vuetify/components/VMain'
import {VMenu} from 'vuetify/components/VMenu'
import {VProgressCircular} from 'vuetify/components/VProgressCircular'
import {VProgressLinear} from 'vuetify/components/VProgressLinear'
import {VSheet} from 'vuetify/components/VSheet'
import {VSnackbar} from 'vuetify/components/VSnackbar'
import {VSpacer} from 'vuetify/components/VGrid'
import {VTab, VTabs} from 'vuetify/components/VTabs'
import {VTable} from 'vuetify/components/VTable'
import {VTextField} from 'vuetify/components/VTextField'
import {VTextarea} from 'vuetify/components/VTextarea'

/**
 * Vuetify set up as BOA, Damien and Diablo set it up: components registered by hand (add each one here when a screen first uses it,
 * so the bundle holds only what the BMU uses), icons from @mdi/js, and control defaults. The light theme is BOA's colours; the dark theme
 * follows Damien's and Diablo's (BOA has none).
 */
export default createVuetify({
  components: {
    VAlert,
    VApp,
    VAppBar,
    VBtn,
    VCard,
    VCardText,
    VChip,
    VDialog,
    VDivider,
    VExpansionPanel,
    VExpansionPanels,
    VExpansionPanelText,
    VExpansionPanelTitle,
    VForm,
    VIcon,
    VLazy,
    VList,
    VListItem,
    VListItemTitle,
    VMain,
    VMenu,
    VProgressCircular,
    VProgressLinear,
    VSheet,
    VSnackbar,
    VSpacer,
    VTab,
    VTable,
    VTabs,
    VTextarea,
    VTextField
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
          creator: '#6b3fa0', // "Needs an Object creator": its own colour, not an error's (design: Roles)
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
          topbar: '#125074',
          warning: '#C74600'
        }
      },
      dark: {
        colors: {
          anchor: '#7cc0e8',
          background: '#0d202c',
          body: '#e6e6e6',
          creator: '#c9a8f5',
          error: '#ff6b6b',
          info: '#61b8ff',
          primary: '#86c8f3',
          secondary: '#4298d1',
          success: '#4fc46a',
          surface: '#15293a',
          'surface-light': '#1e3547',
          tertiary: '#195f8a',
          topbar: '#0c354d',
          warning: '#ffa64d'
        }
      }
    }
  }
})
