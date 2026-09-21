import { LANGUAGES, useI18n } from "../i18n.js";

export default {
  name: "LoginForm",
  props: {
    config: { type: Object, default: null },
  },
  setup(props, { emit }) {
    const { ref } = Vue;
    const { t, locale, setLocale } = useI18n();

    const username = ref("");
    const password = ref("");
    const error = ref("");
    const loading = ref(false);

    async function loginWithPassword() {
      error.value = "";
      loading.value = true;
      try {
        const body = new URLSearchParams({
          username: username.value,
          password: password.value,
        });
        const response = await fetch("/token", {
          method: "POST",
          headers: { "Content-Type": "application/x-www-form-urlencoded" },
          body,
        });
        if (!response.ok) throw new Error("login failed");
        const data = await response.json();
        password.value = "";
        emit("login", data.access_token);
      } catch {
        error.value = t("login_invalid");
      } finally {
        loading.value = false;
      }
    }

    function loginWithWikibase() {
      error.value = "";
      loading.value = true;
      window.location.href = "/oauth/login";
    }

    return {
      props,
      username,
      password,
      error,
      loading,
      loginWithPassword,
      loginWithWikibase,
      t,
      locale,
      setLocale,
      LANGUAGES,
    };
  },
  template: `
    <main class="login-page">
      <article class="login-card">
        <hgroup>
          <h2>{{ t('login_title') }}</h2>
          <p>{{ t('login_subtitle') }}</p>
        </hgroup>
        <div v-if="error" class="error-banner">{{ error }}</div>
        <template v-if="!config?.oauth_configured">
          <form @submit.prevent="loginWithPassword">
            <label>
              {{ t('login_username') }}
              <input v-model="username" name="username" autocomplete="username" required />
            </label>
            <label>
              {{ t('login_password') }}
              <input v-model="password" name="password" type="password" autocomplete="current-password" required />
            </label>
            <button type="submit" :aria-busy="loading" :disabled="loading">
              {{ t('login_submit') }}
            </button>
          </form>
        </template>
        <template v-if="config?.oauth_configured">
          <button type="button" class="secondary" :aria-busy="loading" :disabled="loading" @click="loginWithWikibase">
            {{ t('login_oauth_submit') }}
          </button>
          <p class="login-oauth-version">
            {{ t('login_oauth_version', { version: config.oauth_version }) }}
          </p>
        </template>
        <div class="login-lang">
          <select :value="locale" @change="setLocale($event.target.value)">
            <option v-for="(label, code) in LANGUAGES" :key="code" :value="code">{{ label }}</option>
          </select>
        </div>
      </article>
    </main>
  `,
};
