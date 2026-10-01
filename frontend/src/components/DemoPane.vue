<script setup lang="ts">
// Demo tools (demo builds only; see lib/demo.ts): slow the transfers down, make the simulated CollectionSpace fail
// or change its terms, reset things, and how to run the check scripts. Collapsible; remembered in this browser.
import { computed, onBeforeUnmount, onMounted, reactive, ref } from "vue";
import ChevronIcon from "./ChevronIcon.vue";
import { ApiError } from "../api";
import { COMMANDS, demoApi, demoSummary, failureText, speedLabel, speedText, type DemoStatus } from "../lib/demo";

const emit = defineEmits<{ jobsDeleted: [message: string] }>();

const OPEN_KEY = "bmuDemoPaneOpen";
function readOpen(): boolean {
  try { return localStorage.getItem(OPEN_KEY) !== "0"; } catch { return true; }
}
const open = ref(readOpen());
function toggle() {
  open.value = !open.value;
  try { localStorage.setItem(OPEN_KEY, open.value ? "1" : "0"); } catch { /* private window: not remembered */ }
}

const st = ref<DemoStatus | null>(null);
const off = ref(false); // the server's demo mode is off (BMU_DEMO)
const busy = ref(false);
const msg = ref("");
const err = ref("");
const confirmDeleteAll = ref(false);
const objects = ref<{ objectNumber: string; note: string; deleted: boolean; sensitivity?: unknown }[] | null>(null);

const BROWSER_SPEEDS = [0, 10, 5, 2, 1, 0.5];
const RUN_SPEEDS = [0, 20, 5, 2, 1];
const DELAYS = [0, 1, 2, 5, 10];
const STATUSES: [number, string][] = [[500, "500 server error"], [503, "503 unavailable"], [400, "400 rejected"], [401, "401 sign-in"],
  [403, "403 permission"], [409, "409 account inactive"], [413, "413 file too large"], [415, "415 file type"]];

const fail = reactive({ step: "upload", status: 500, match: "", count: 1, client: "worker" });
const term = reactive({ name: "", how: "deleted", to: "" });
const lang = reactive({ code: "", how: "delete", to: "" });

const summary = computed(() => demoSummary(st.value));
const sim = computed(() => st.value?.sim ?? null);
const termChanges = computed(() => {
  const s = sim.value;
  if (!s) return [];
  const name = (k: string) => s.term_names?.[k] ?? k;
  return [
    ...Object.entries(s.term_states).map(([k, v]) => `${name(k)}: ${v === "gone" ? "gone (404, as if merged or purged)" : "deleted"}`),
    ...Object.entries(s.term_renames).map(([k, v]) => `${name(k)}: renamed “${v}”`),
    ...s.deleted_languages.map((c) => `language ${c}: removed`),
    ...Object.entries(s.language_renames).map(([c, v]) => `language ${c}: renamed “${v}”`),
  ];
});

async function refresh() {
  try {
    st.value = await demoApi.status();
    off.value = false;
    if (!term.name && st.value.sim) term.name = st.value.sim.people[0] ?? "";
    if (!lang.code && st.value.sim) lang.code = Object.keys(st.value.sim.languages)[0] ?? "";
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) off.value = true;
    else err.value = (e as Error).message;
  }
}

async function run(what: () => Promise<unknown>, done: string) {
  busy.value = true;
  err.value = "";
  msg.value = "";
  try {
    await what();
    msg.value = done;
    await refresh();
  } catch (e) {
    err.value = (e as Error).message;
  } finally {
    busy.value = false;
  }
}

const setBrowserSpeed = (mbps: number) => run(() => demoApi.browserUpload(mbps),
  `Browser uploads: ${speedText(mbps)}, for uploads that start from now on.`);
const setRunSpeed = (mbps: number) => run(() => demoApi.sim("slow", { seconds: sim.value?.delay ?? 0, upload_mbps: mbps }),
  `File uploads to CollectionSpace in job runs: ${speedText(mbps)}.`);
const setDelay = (seconds: number) => run(() => demoApi.sim("slow", { seconds, upload_mbps: sim.value?.upload_mbps ?? 0 }),
  seconds ? `Each create and upload in a run now takes ${seconds} s longer.` : "No added delay in runs.");
const addFailure = () => run(() => demoApi.sim("fail", { ...fail }), failureText(fail.step, fail.status, fail.count));
const clearFailures = () => run(() => demoApi.sim("clear-failures"), "No failures set.");
const changeTerm = () => run(() => (term.how === "rename"
  ? demoApi.sim("rename-term", { name: term.name, to: term.to })
  : demoApi.sim("delete-term", { name: term.name, how: term.how })), `“${term.name}” changed in CollectionSpace.`);
const changeLanguage = () => run(() => (lang.how === "rename"
  ? demoApi.sim("rename-language", { code: lang.code, to: lang.to })
  : demoApi.sim("delete-language", { code: lang.code })), `Language ${lang.code} changed in CollectionSpace.`);
const resetSim = () => run(() => demoApi.sim("reset"),
  "The simulated CollectionSpace is reset: its records, terms, failures and speeds are back to the start.");

async function deleteAllJobs(andReset = false) {
  confirmDeleteAll.value = false;
  await run(async () => {
    const r = await demoApi.deleteAllJobs();
    if (andReset) {
      await demoApi.sim("reset");
      await demoApi.browserUpload(0);
    }
    const kept = r.skipped.length ? ` Kept ${r.skipped.length} running: ${r.skipped.join(", ")}.` : "";
    emit("jobsDeleted", `Demo tools deleted ${r.deleted} job${r.deleted === 1 ? "" : "s"}.${kept}`);
  }, andReset ? "Everything is reset: no jobs, and the simulator and upload speeds are back to the start." : "Jobs deleted.");
}

async function loadObjects(e: Event) {
  if ((e.target as HTMLDetailsElement).open && !objects.value) {
    try { objects.value = (await demoApi.objects()).objects; } catch (x) { err.value = (x as Error).message; }
  }
}

const copied = ref("");
async function copy(title: string, text: string) {
  try {
    await navigator.clipboard.writeText(text);
    copied.value = title;
    setTimeout(() => { if (copied.value === title) copied.value = ""; }, 1500);
  } catch { /* clipboard not allowed: the text can still be selected */ }
}

let timer: ReturnType<typeof setInterval> | undefined;
onMounted(() => {
  refresh();
  timer = setInterval(() => { if (open.value && !busy.value) refresh(); }, 10000); // failures get used up during runs
});
onBeforeUnmount(() => clearInterval(timer));
</script>

<template>
  <section class="demo-pane" :class="{ collapsed: !open }" aria-label="Demo tools">
    <div class="demo-head">
      <button class="chevron" :class="{ open }" :aria-expanded="open" aria-controls="demoBody"
              :aria-label="open ? 'Hide demo tools' : 'Show demo tools'" :title="open ? 'Hide demo tools' : 'Show demo tools'" @click="toggle">
        <ChevronIcon />
      </button>
      <strong>Demo tools</strong>
      <span class="badge b-accent" title="Only in demo builds (npm run dev, npm run build:demo) with BMU_DEMO=true on the server; never in production">Demo build only</span>
      <span v-if="!open" class="demo-summary">{{ off ? "Off in this environment; commands only" : summary }}</span>
    </div>

    <div v-show="open" id="demoBody" class="demo-body">
      <div v-if="off" class="msg msg-info">Demo tools are off in this environment: they need the simulated CollectionSpace and
        <code>BMU_DEMO=true</code>, as in <code>./bmu up sim</code>. The check-script commands below work everywhere.</div>
      <template v-else-if="st">
        <p class="sub demo-intro">For demos and testing with the simulated CollectionSpace ({{ st.cspaceUrl }}). None of this is
          part of the BMU; production builds leave it out.<template v-if="st.alwaysRunTime"> Every moment is a run time
          (BMU_ALWAYS_RUN_TIME), so submitted jobs start at once.</template></p>
        <div v-if="st.simError" class="msg msg-warn">{{ st.simError }}</div>
        <div v-if="msg" class="msg msg-info" role="status">{{ msg }}</div>
        <div v-if="err" class="msg msg-warn" role="alert">{{ err }}</div>

        <div class="demo-grid">
          <div class="demo-box">
            <h3>Slow down file transfers</h3>
            <label class="demo-row"><span>Browser uploads (Create / edit job)</span>
              <select :value="st.browserUploadMbps" :disabled="busy" @change="setBrowserSpeed(+($event.target as HTMLSelectElement).value)">
                <option v-for="v in BROWSER_SPEEDS" :key="v" :value="v">{{ speedLabel(v) }}</option>
              </select></label>
            <template v-if="sim">
              <label class="demo-row"><span>File uploads to CollectionSpace (job runs)</span>
                <select :value="sim.upload_mbps" :disabled="busy" @change="setRunSpeed(+($event.target as HTMLSelectElement).value)">
                  <option v-for="v in RUN_SPEEDS" :key="v" :value="v">{{ speedLabel(v) }}</option>
                </select></label>
              <label class="demo-row"><span>Added delay per create or upload (job runs)</span>
                <select :value="sim.delay" :disabled="busy" @change="setDelay(+($event.target as HTMLSelectElement).value)">
                  <option v-for="v in DELAYS" :key="v" :value="v">{{ v ? `${v} s` : "None" }}</option>
                </select></label>
            </template>
            <p class="sub">A browser upload speed applies to uploads that start after you set it. Use large sample files (50 MB or
              more): the first few MB of each file fill network buffers at once, so small files jump to 100%.</p>
          </div>

          <div v-if="sim" class="demo-box">
            <h3>Make CollectionSpace fail</h3>
            <div class="demo-inline">
              <label>Step <select v-model="fail.step"><option v-for="s in sim.steps" :key="s" :value="s">{{ s }}</option></select></label>
              <label>With <select v-model.number="fail.status"><option v-for="[c, l] in STATUSES" :key="c" :value="c">{{ l }}</option></select></label>
              <label>Times <input v-model.number="fail.count" type="number" min="0" max="99" class="demo-num" title="0: until cleared" /></label>
            </div>
            <div class="demo-inline">
              <label>Only if it mentions <input v-model="fail.match" type="text" placeholder="any document" class="demo-text"
                     title="Part of an identification number, filename, object number, group title or term" /></label>
              <label title="Job runs only (the editor's checks unaffected), or every request"><select v-model="fail.client">
                <option value="worker">in job runs</option><option value="any">everywhere</option></select></label>
              <button :disabled="busy" @click="addFailure">Add failure</button>
            </div>
            <ul v-if="sim.rules.length" class="demo-list">
              <li v-for="(r, i) in sim.rules" :key="i">{{ r.step }} → {{ r.effect || r.status }}{{ r.match ? ` if “${r.match}”` : "" }},
                {{ r.count ? `${r.left} of ${r.count} left` : "until cleared" }}{{ r.client === "any" ? ", everywhere" : "" }}</li>
            </ul>
            <button v-if="sim.rules.length" class="link" :disabled="busy" @click="clearFailures">Clear failures</button>
          </div>

          <div v-if="sim" class="demo-box">
            <h3>Change terms in CollectionSpace</h3>
            <div class="demo-inline">
              <select v-model="term.name" aria-label="Person or organization">
                <optgroup label="Persons"><option v-for="p in sim.people" :key="p" :value="p">{{ p }}</option></optgroup>
                <optgroup label="Organizations"><option v-for="o in sim.orgs" :key="o" :value="o">{{ o }}</option></optgroup>
              </select>
              <select v-model="term.how" aria-label="Change">
                <option value="deleted">Delete (soft)</option><option value="gone">Gone (404, as if merged)</option><option value="rename">Rename to…</option>
              </select>
              <input v-if="term.how === 'rename'" v-model="term.to" type="text" class="demo-text" aria-label="New name" placeholder="New name" />
              <button :disabled="busy || (term.how === 'rename' && !term.to.trim())" @click="changeTerm">Apply</button>
            </div>
            <div class="demo-inline">
              <select v-model="lang.code" aria-label="Language">
                <option v-for="(n, c) in sim.languages" :key="c" :value="c">{{ n }} ({{ c }})</option>
              </select>
              <select v-model="lang.how" aria-label="Change"><option value="delete">Remove</option><option value="rename">Rename to…</option></select>
              <input v-if="lang.how === 'rename'" v-model="lang.to" type="text" class="demo-text" aria-label="New name" placeholder="New name" />
              <button :disabled="busy || (lang.how === 'rename' && !lang.to.trim())" @click="changeLanguage">Apply</button>
            </div>
            <ul v-if="termChanges.length" class="demo-list"><li v-for="t in termChanges" :key="t">{{ t }}</li></ul>
            <p class="sub">Documents using a changed term show it in the editor's checks, and a run checks again before each document.</p>
          </div>

          <div class="demo-box">
            <h3>Reset</h3>
            <div class="demo-inline">
              <button v-if="sim" :disabled="busy" @click="resetSim">Reset simulated CollectionSpace</button>
              <button :disabled="busy || !st.browserUploadMbps" @click="setBrowserSpeed(0)">Browser uploads at full speed</button>
            </div>
            <div v-if="!confirmDeleteAll" class="demo-inline">
              <button :disabled="busy" @click="confirmDeleteAll = true">Delete all jobs…</button>
            </div>
            <div v-else class="bulk-confirm" role="alert">
              <span>Delete every job in this tenant (drafts, queued and finished), except running ones? Their files are
                removed from the BMU; records already created in CollectionSpace stay.</span>
              <div class="demo-inline">
                <button class="danger" :disabled="busy" @click="deleteAllJobs(false)">Delete all jobs</button>
                <button class="danger" :disabled="busy" @click="deleteAllJobs(true)">Delete all jobs and reset everything</button>
                <button @click="confirmDeleteAll = false">Cancel</button>
              </div>
            </div>
            <p class="sub">Resetting the simulator also forgets the records earlier runs created in it.</p>
          </div>
        </div>

        <details v-if="sim" class="demo-more" @toggle="loadObjects">
          <summary>Sample objects in the simulated CollectionSpace</summary>
          <p v-if="!objects" class="sub">Loading…</p>
          <table v-else class="demo-table">
            <thead><tr><th>Object number</th><th>What it's for</th></tr></thead>
            <tbody><tr v-for="o in objects" :key="o.objectNumber">
              <td>{{ o.objectNumber }}</td><td>{{ o.note }}{{ o.deleted ? " (deleted)" : "" }}{{ o.sensitivity ? " · protected" : "" }}</td></tr></tbody>
          </table>
        </details>
      </template>
      <p v-else class="sub">Loading…</p>

      <details class="demo-more">
        <summary>Check scripts and other commands</summary>
        <div v-for="c in COMMANDS" :key="c.title" class="demo-cmd">
          <div class="demo-cmd-head"><strong>{{ c.title }}</strong>
            <button class="link" @click="copy(c.title, c.lines)">{{ copied === c.title ? "Copied" : "Copy" }}</button></div>
          <p class="sub">{{ c.note }}</p>
          <pre>{{ c.lines }}</pre>
        </div>
      </details>
    </div>
  </section>
</template>

<style scoped>
.demo-pane { border: 1px dashed var(--border-strong); border-radius: 12px; padding: 8px 14px; margin-bottom: 14px; background: var(--surface-2); font-size: 13px; }
.demo-head { display: flex; align-items: center; gap: 8px; margin-left: -6px; min-width: 0; }
.demo-summary { color: var(--text-muted); font-size: 12px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; min-width: 0; }
.demo-body { margin-top: 6px; }
.demo-intro { margin: 0 0 8px; }
.demo-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 10px; margin: 8px 0; }
.demo-box { border: 1px solid var(--border); border-radius: 8px; padding: 10px 12px; display: flex; flex-direction: column; gap: 6px; }
.demo-box h3 { font-size: 13px; margin: 0 0 2px; }
.demo-box .sub { margin: 2px 0 0; }
.demo-row { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.demo-inline { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.demo-inline label { display: inline-flex; align-items: center; gap: 4px; }
.demo-num { width: 56px; }
.demo-text { width: 160px; }
.demo-list { margin: 2px 0; padding-left: 18px; font-size: 12px; color: var(--text-secondary); }
.demo-more { margin-top: 8px; }
.demo-more summary { cursor: pointer; font-weight: 600; }
.demo-table { border-collapse: collapse; font-size: 12px; margin-top: 6px; }
.demo-table th, .demo-table td { text-align: left; padding: 3px 10px 3px 0; border-bottom: 1px solid var(--border); }
.demo-cmd { margin-top: 10px; }
.demo-cmd-head { display: flex; align-items: center; gap: 10px; }
.demo-cmd .sub { margin: 2px 0 4px; }
.demo-cmd pre { margin: 0; padding: 8px 10px; background: var(--surface-1); border-radius: 6px; font-size: 12px; overflow-x: auto; white-space: pre; }
</style>
