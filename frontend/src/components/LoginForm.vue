<script setup lang="ts">
import { ref } from "vue";
import { api } from "../api";
import type { Me } from "../types";

const emit = defineEmits<{ signedIn: [me: Me] }>();
const username = ref("");
const password = ref("");
const error = ref("");
const busy = ref(false);

async function submit() {
  busy.value = true;
  error.value = "";
  try {
    emit("signedIn", await api.login(username.value.trim(), password.value));
  } catch (e) {
    error.value = (e as Error).message;
  } finally {
    password.value = "";
    busy.value = false;
  }
}
</script>

<template>
  <div class="card login">
    <h1>Bulk Media Uploader</h1>
    <p class="subtitle">Sign in with your CollectionSpace account. Your password is used only for your uploads and is deleted when they finish.</p>
    <form @submit.prevent="submit">
      <label class="field"><span>CollectionSpace username</span>
        <input v-model="username" type="text" autocomplete="username" required />
      </label>
      <label class="field"><span>Password</span>
        <input v-model="password" type="password" autocomplete="current-password" required />
      </label>
      <div v-if="error" class="msg msg-block" role="alert">{{ error }}</div>
      <button class="primary" type="submit" :disabled="busy">{{ busy ? "Signing in…" : "Sign in" }}</button>
    </form>
  </div>
</template>
