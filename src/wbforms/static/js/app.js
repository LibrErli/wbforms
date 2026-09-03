import {
  computed,
  createApp,
  nextTick,
  onMounted,
  reactive,
  ref,
  watch,
} from "vue";
import { apiFetch } from "./api.js";
import EntityEditor from "./components/EntityEditor.js";
import FieldInput from "./components/FieldInput.js";
import Icon from "./components/Icon.js";
import LoginForm from "./components/LoginForm.js";
import { useI18n } from "./i18n.js";

// Expose Vue composition API globally so component files can do `const { ref } = Vue`
window.Vue = { ref, reactive, computed, watch, nextTick, onMounted };

function decodeJwt(token) {
  if (!token) return null;
  const parts = token.split(".");
  if (parts.length !== 3) return null;
  try {
    const padded = parts[1].replace(/-/g, "+").replace(/_/g, "/");
    return JSON.parse(atob(padded));
  } catch {
    return null;
  }
}

function usernameFromToken(token) {
  return decodeJwt(token)?.sub ?? null;
}

const App = {
  components: { LoginForm, EntityEditor },
  setup() {
    const { t, locale } = useI18n();

    // Pick up an OAuth callback token delivered via #token=... fragment.
    const hash = window.location.hash || "";
    const m = hash.match(/[#&]token=([^&]+)/);
    if (m) {
      localStorage.setItem("token", decodeURIComponent(m[1]));
      history.replaceState(
        null,
        "",
        window.location.pathname + window.location.search,
      );
    }

    const initialToken = localStorage.getItem("token");
    const state = reactive({
      token: initialToken,
      username: usernameFromToken(initialToken),
      schema: null,
      schemaError: null,
      config: null,
      configError: null,
    });

    const isLoggedIn = computed(() => !!state.token);

    async function loadConfig() {
      try {
        state.config = await apiFetch("/api/config");
      } catch (e) {
        state.configError = e.message;
      }
    }

    async function loadSchema() {
      if (!isLoggedIn.value) return;
      try {
        state.schema = await apiFetch(`/api/schema/entities?language=${locale.value}`);
      } catch (e) {
        state.schemaError = e.message;
      }
    }

    function onLogin(token) {
      state.token = token;
      state.username = usernameFromToken(token);
      state.schemaError = null;
      loadSchema();
    }

    function onLogout() {
      state.token = null;
      state.username = null;
      state.schema = null;
      state.schemaError = null;
    }

    loadConfig();
    loadSchema();

    // Reload schema when language changes
    watch(() => locale.value, () => {
      if (isLoggedIn.value) {
        loadSchema();
      }
    });

    return { state, isLoggedIn, onLogin, onLogout, t };
  },
  template: `
    <div v-if="!state.config && !state.configError" style="padding:2rem;text-align:center">
      <span class="spinner"></span>
    </div>
    <login-form v-else-if="!isLoggedIn" :config="state.config" @login="onLogin" />
    <div v-else-if="!state.schema && !state.schemaError" style="padding:2rem;text-align:center">
      <span class="spinner"></span> {{ t('app_loading_schema') }}
    </div>
    <div v-else-if="state.schemaError" class="error-banner" style="margin:2rem">
      {{ t('app_schema_error', { error: state.schemaError }) }}
    </div>
    <entity-editor v-else :schema="state.schema" :username="state.username" @logout="onLogout" />

    <footer style="margin-top: 2rem; padding: 1rem; border-top: 1px solid #ddd; background: #f9f9f9; display: flex; justify-content: space-between; align-items: center;">
      <div>
       <a href="https://säbig.de"><img src="/static/images/saebig_logo.svg" alt="Logo" style="height: 40px; margin-right: 1rem; vertical-align: middle;"></a>  
       <a href="https://saxorum.de"><img src="/static/images/sxrmLogo.svg" alt="Logo" style="height: 30px; margin-right: 1rem; vertical-align: middle;"></a>
       <a href="https://www.saxorum.de/impressum" class="link-btn" style="text-decoration:none; font-size: 0.65rem;">{{ t('footer_impressum') }}</a>
      </div>
      <div>
        <a href="https://github.com/FactGrid/wbforms" style="color: #333; text-decoration: none;" aria-label="GitHub" title="derrived from FactGrid/wbforms">
          <img src="/static/images/github.png" style="height: 30px;"/>
        </a>
      </div>
    </footer>
  `,
};

const app = createApp(App);
// Register FieldInput globally so SourceBlockEditor can render `<field-input>` without
// a static import (avoids a SourceBlockEditor ↔ FieldInput ESM circular dependency).
app.component("FieldInput", FieldInput);
// Icons are referenced from every component template; global registration keeps imports light.
app.component("Icon", Icon);
app.mount("#app");
