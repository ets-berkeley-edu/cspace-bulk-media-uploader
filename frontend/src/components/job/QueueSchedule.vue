<template>
  <div id="queue-schedule">
    <v-alert
      v-if="schedule.paused"
      id="queue-paused"
      class="mb-2"
      density="compact"
      role="status"
      type="warning"
      variant="tonal"
    >
      {{ pausedBanner(schedule.paused) }}
    </v-alert>
    <v-alert
      id="schedule-banner"
      class="mb-2"
      density="compact"
      type="info"
      variant="tonal"
    >
      {{ scheduleBanner(schedule) }}
    </v-alert>
    <div v-if="schedule.alwaysRunTime" id="schedule-development-setting" class="mb-2 text-caption text-medium-emphasis">
      Development setting: every moment counts as run time.
    </div>
    <div v-if="!scheduler" id="schedule-scheduler-only" class="mb-2 text-caption text-medium-emphasis">
      Only BMU schedulers can change the schedule or the order of the queue.
    </div>
    <div v-if="scheduler" class="align-center d-flex flex-wrap mb-3 schedule-tools">
      <v-btn
        id="schedule-settings-btn"
        :disabled="!!settings"
        size="small"
        variant="outlined"
        @click="openSettings"
      >
        Schedule settings…
      </v-btn>
      <v-btn
        v-if="schedule.paused"
        id="resume-queue-btn"
        :disabled="isResuming"
        size="small"
        variant="outlined"
        @click="resume"
      >
        Resume queue
      </v-btn>
      <v-btn
        v-else
        id="pause-queue-btn"
        :disabled="!!pausing"
        size="small"
        title="Stop new jobs from starting; a running job finishes"
        variant="outlined"
        @click="pausing = {reason: '', error: '', busy: false}"
      >
        Pause queue…
      </v-btn>
    </div>
    <v-sheet
      v-if="scheduler && pausing && !schedule.paused"
      id="pause-queue-panel"
      border
      class="mb-3 pa-3 schedule-panel text-body-2"
      rounded
    >
      <div class="align-center d-flex flex-wrap panel-row">
        <label class="font-weight-medium" for="pause-reason">Reason for pausing</label>
        <input
          id="pause-reason"
          v-model="pausing.reason"
          class="native-input pause-reason"
          maxlength="200"
          :placeholder="`Shown to everyone in ${tenant.name}`"
          type="text"
        >
        <v-btn
          id="pause-queue-confirm-btn"
          color="primary"
          :disabled="pausing.busy"
          size="small"
          @click="pause"
        >
          Pause
        </v-btn>
        <v-btn
          id="pause-queue-cancel-btn"
          size="small"
          variant="outlined"
          @click="pausing = null"
        >
          Cancel
        </v-btn>
      </div>
      <div class="mt-2 text-caption text-medium-emphasis">
        A running job finishes; no other job starts until a BMU scheduler resumes the queue. Queued jobs’ sign-in clocks keep running.
      </div>
      <v-alert
        v-if="pausing.error"
        id="pause-queue-error"
        class="mt-2"
        density="compact"
        type="error"
        variant="tonal"
      >
        {{ pausing.error }}
      </v-alert>
    </v-sheet>
    <v-sheet
      v-if="scheduler && settings"
      id="schedule-settings-panel"
      aria-label="Schedule settings"
      border
      class="mb-3 pa-3 schedule-panel text-body-2"
      role="group"
      rounded
    >
      <div class="font-weight-bold mb-2">Schedule for {{ tenant.name }}</div>
      <div class="align-center d-flex flex-wrap mb-2 panel-row schedule-days">
        <span class="font-weight-medium">Run days</span>
        <label v-for="day in DAY_ORDER" :key="day" :for="`schedule-day-${day}`">
          <input
            :id="`schedule-day-${day}`"
            :checked="settings.days.includes(day)"
            class="checkbox schedule-day"
            type="checkbox"
            @change="event => toggleDay(day, (event.target as HTMLInputElement).checked)"
          >
          {{ DAY_NAMES[day] }}
        </label>
      </div>
      <div class="align-center d-flex flex-wrap mb-2 panel-row">
        <label class="font-weight-medium" for="schedule-start">Start time</label>
        <input
          id="schedule-start"
          v-model="settings.start"
          class="native-input"
          type="time"
        >
        <label for="schedule-end-on">
          <input
            id="schedule-end-on"
            v-model="settings.endOn"
            class="checkbox"
            type="checkbox"
          >
          Don’t start new jobs after
        </label>
        <input
          id="schedule-end"
          v-model="settings.end"
          aria-label="End time"
          class="native-input"
          :disabled="!settings.endOn"
          type="time"
        >
        <span class="text-caption text-medium-emphasis">Pacific time</span>
      </div>
      <div class="mb-2 text-caption text-medium-emphasis">
        Run days can’t be more than 3 days apart: a queued job’s saved sign-in lasts 72 hours. An end time may be after midnight.
      </div>
      <v-alert
        v-if="settings.error"
        id="schedule-settings-error"
        class="mb-2"
        density="compact"
        type="error"
        variant="tonal"
      >
        {{ settings.error }}
      </v-alert>
      <div class="align-center d-flex panel-row">
        <v-btn
          id="schedule-save-btn"
          color="primary"
          :disabled="settings.busy"
          size="small"
          @click="save"
        >
          Save
        </v-btn>
        <v-btn
          id="schedule-cancel-btn"
          size="small"
          variant="outlined"
          @click="settings = null"
        >
          Cancel
        </v-btn>
      </div>
    </v-sheet>
  </div>
</template>

<script setup lang="ts">
import type {PropType} from 'vue'
import {ref} from 'vue'
import type {Schedule, TenantInfo} from '@/types'
import {DAY_NAMES, DAY_ORDER, pausedBanner, scheduleBanner, scheduleShort, scheduleSummary, whenLabel} from '@/lib/schedule'
import {api} from '@/api'

/**
 * The Job queue's schedule (design: Job scheduling): the banner with the run times and the next one, and, for BMU
 * schedulers, Schedule settings, Pause queue and Resume queue. What the server refuses (422) shows in the panel.
 */
const props = defineProps({
  schedule: {
    required: true,
    type: Object as PropType<Schedule>
  },
  // The signed-in user has the BMU_Scheduler role.
  scheduler: {
    required: false,
    type: Boolean
  },
  tenant: {
    required: true,
    type: Object as PropType<TenantInfo>
  }
})
// The schedule changed: the new one, and what to tell the user.
const emit = defineEmits<{changed: [schedule: Schedule, message: string], error: [message: string]}>()

const settings = ref<{days: number[], start: string, endOn: boolean, end: string, error: string, busy: boolean} | null>(null)
const pausing = ref<{reason: string, error: string, busy: boolean} | null>(null)
const isResuming = ref(false)

const openSettings = () => {
  const s = props.schedule
  settings.value = {days: [...s.days], start: s.start, endOn: !!s.end, end: s.end || '06:00', error: '', busy: false}
}

const toggleDay = (day: number, on: boolean) => {
  const edit = settings.value!
  edit.days = on ? [...new Set([...edit.days, day])].sort((a, b) => a - b) : edit.days.filter(d => d !== day)
}

const save = async () => {
  const edit = settings.value
  if (!edit) {
    return
  }
  if (edit.endOn && !edit.end) {
    edit.error = 'Enter the end time, or untick “Don’t start new jobs after”.'
    return
  }
  const before = props.schedule
  edit.busy = true
  try {
    const s = await api.putSchedule({days: edit.days, start: edit.start, end: edit.endOn ? edit.end : ''})
    settings.value = null
    emit('changed', s, scheduleShort(before) === scheduleShort(s) ? 'The schedule didn’t change.'
      : `Schedule saved. ${scheduleSummary(s)}` + (s.nextRunAt ? ` Next run time: ${whenLabel(s.nextRunAt, {today: true})}.` : ''))
  } catch (e) {
    edit.error = (e as Error).message
  } finally {
    edit.busy = false
  }
}

const pause = async () => {
  const edit = pausing.value
  if (!edit) {
    return
  }
  const reason = edit.reason.trim()
  if (!reason) {
    edit.error = 'Enter a reason, so others know why the queue is paused.'
    return
  }
  edit.busy = true
  try {
    const s = await api.pauseQueue(reason)
    pausing.value = null
    emit('changed', s, 'You paused the queue. A running job finishes; no other job starts until a BMU scheduler resumes it.')
  } catch (e) {
    edit.error = (e as Error).message
  } finally {
    edit.busy = false
  }
}

const resume = async () => {
  isResuming.value = true
  try {
    const s = await api.resumeQueue()
    emit('changed', s, 'You resumed the queue.' + (s.nextRunAt ? ` Queued jobs start at the next run time, ${whenLabel(s.nextRunAt)}.` : ''))
  } catch (e) {
    emit('error', (e as Error).message)
  } finally {
    isResuming.value = false
  }
}
</script>

<style scoped>
.schedule-tools,
.panel-row {
  gap: 8px 12px;
}
.pause-reason {
  flex: 1 1 280px;
  max-width: 420px;
}
</style>
