import { apiFetch } from "../api.js";
import { LANGUAGES, useI18n } from "../i18n.js";
import CommitDialog from "./CommitDialog.js";
import FieldInput from "./FieldInput.js";
import ItemSearchInput from "./ItemSearchInput.js";
import StatementListEditor from "./StatementListEditor.js";

function isEmptyValue(v) {
  return v == null || v === "" || (Array.isArray(v) && v.length === 0);
}

function stringifyForCompare(v) {
  if (v == null) return null;
  return Array.isArray(v) ? v.join("") : String(v);
}

export default {
  name: "EntityEditor",
  components: {
    FieldInput,
    StatementListEditor,
    CommitDialog,
    ItemSearchInput,
  },
  props: {
    schema: { default: null },
    username: { type: String, default: null },
  },
  emits: ["logout"],
  setup(props, { emit }) {
    const { ref, reactive, computed, watch, onMounted, nextTick } = Vue;
    const { t, locale, setLocale } = useI18n();

    const selectedEntityName = ref("");
    const qidInput = ref("");
    const loadedData = ref(null);
    const pendingData = reactive({});
    const isNew = ref(false);
    const loadError = ref("");
    const loadLoading = ref(false);
    const success = ref("");
    const commitOpen = ref(false);

    const pendingStatements = reactive({});
    const clearSignal = ref(0);

    function parseFormUrl() {
      const parts = window.location.pathname.split("/").filter(Boolean);
      if (parts[0] !== "form") return null;
      return { entitySlug: parts[1] ?? null, action: parts[2] ?? null };
    }

    function pushFormUrl(entitySlug, action = null) {
      const path = action
        ? `/form/${entitySlug}/${action}`
        : `/form/${entitySlug}`;
      history.pushState(null, "", path);
    }

    const entities = computed(() =>
      Array.isArray(props.schema)
        ? props.schema
        : (props.schema?.entities ?? []),
    );
    const selectedEntity = computed(
      () =>
        entities.value.find((e) => e.name === selectedEntityName.value) ?? null,
    );
    const simpleFields = computed(() =>
      (selectedEntity.value?.fields ?? []).filter(
        (f) => f.field_type !== "statement_list",
      ),
    );
    const statementFields = computed(() =>
      (selectedEntity.value?.fields ?? []).filter(
        (f) => f.field_type === "statement_list",
      ),
    );
    const loadedQid = computed(() => loadedData.value?.qid ?? null);

    // Pending-change count for the commit button badge. Best-effort: counts
    // simple-field diffs + source-list diffs + statement ops. Detailed diff
    // still lives in CommitDialog; this is just for the "(N)" indicator.
    const pendingCount = computed(() => {
      if (!selectedEntity.value) return 0;
      let n = 0;
      for (const [k, v] of Object.entries(pendingData)) {
        const isSources = k.endsWith("_sources");
        const oldVal = loadedData.value?.[k];
        const newEmpty = isEmptyValue(v);
        const oldEmpty = isEmptyValue(oldVal);
        if (newEmpty && oldEmpty) continue;
        if (isSources) {
          if (JSON.stringify(v ?? []) !== JSON.stringify(oldVal ?? [])) n++;
        } else if (
          stringifyForCompare(newEmpty ? null : v) !==
          stringifyForCompare(oldVal)
        ) {
          n++;
        }
      }
      for (const key of Object.keys(pendingStatements)) {
        n += pendingStatements[key].ops?.length ?? 0;
      }
      return n;
    });
    const hasChanges = computed(() => pendingCount.value > 0);

    const isValidQid = computed(() => {
      const q = qidInput.value.trim();
      return q && /^Q\d+$/i.test(q);
    });

    function resetForm() {
      loadedData.value = null;
      Object.keys(pendingData).forEach((k) => {
        delete pendingData[k];
      });
      Object.keys(pendingStatements).forEach((k) => {
        delete pendingStatements[k];
      });
      clearSignal.value++;
      if (selectedEntity.value) {
        selectedEntity.value.fields.forEach((f) => {
          if (f.field_type === "statement_list") return;
          pendingData[f.name] = f.field_type === "list" ? [] : "";
          if (f.supports_references) {
            pendingData[`${f.name}_sources`] = [];
          }
          if (f.calendar_field) {
            pendingData[f.calendar_field] = f.field_type === "list" ? [] : "";
          }
        });
      }
      loadError.value = "";
      success.value = "";
    }

    let initializing = false;

    watch(selectedEntityName, () => {
      qidInput.value = "";
      isNew.value = false;
      resetForm();
      if (!initializing && selectedEntityName.value) {
        pushFormUrl(selectedEntityName.value.toLowerCase());
      }
    });

    // Re-apply a freshly loaded/saved entity to the form: set it as the loaded baseline, clear and
    // repopulate the simple-field pendingData from it, and bump clearSignal so each
    // StatementListEditor reloads its rows from the server. Shared by load() and onSaved() so the
    // whole form (fields, sources, statement tables) always reflects the persisted item.
    function applyEntity(data) {
      loadedData.value = data;
      Object.keys(pendingStatements).forEach((k) => {
        delete pendingStatements[k];
      });
      clearSignal.value++;
      Object.keys(pendingData).forEach((k) => {
        delete pendingData[k];
      });
      if (!data) return;
      (selectedEntity.value?.fields ?? []).forEach((f) => {
        if (f.field_type === "statement_list") return;
        pendingData[f.name] =
          data[f.name] ?? (f.field_type === "list" ? [] : "");
        if (f.supports_references) {
          pendingData[`${f.name}_sources`] = data[`${f.name}_sources`] ?? [];
        }
        if (f.calendar_field) {
          pendingData[f.calendar_field] =
            data[f.calendar_field] ?? (f.field_type === "list" ? [] : "");
        }
      });
    }

    async function load() {
      if (!selectedEntity.value || !qidInput.value.trim()) return;
      loadLoading.value = true;
      loadError.value = "";
      try {
        const prefix = selectedEntity.value.endpoint_prefix;
        const data = await apiFetch(`${prefix}/${qidInput.value.trim()}`);
        if (!data) return;
        isNew.value = false;
        pushFormUrl(
          selectedEntityName.value.toLowerCase(),
          qidInput.value.trim(),
        );
        applyEntity(data);
      } catch (e) {
        loadError.value = e.message;
      } finally {
        loadLoading.value = false;
      }
    }

    function startNew() {
      qidInput.value = "";
      isNew.value = true;
      resetForm();
      if (selectedEntityName.value) {
        pushFormUrl(selectedEntityName.value.toLowerCase(), "new");
      }
    }

    function setCalendar(field, value) {
      if (!field.calendar_field) return;
      pendingData[field.calendar_field] = value;
    }

    function onPendingChange(fieldName, ops, fieldConfig) {
      if (ops.length === 0) {
        delete pendingStatements[fieldName];
      } else {
        pendingStatements[fieldName] = { ops, field: fieldConfig };
      }
    }

    function onSaved(entity) {
      isNew.value = false;
      applyEntity(entity);
      if (entity?.qid) {
        qidInput.value = entity.qid;
        history.replaceState(
          null,
          "",
          `/form/${selectedEntityName.value.toLowerCase()}/${entity.qid}`,
        );
      }
      success.value = t("entity_saved", { qid: entity?.qid ?? "(unknown)" });
      setTimeout(() => {
        success.value = "";
      }, 5000);
    }

    function logout() {
      localStorage.removeItem("token");
      emit("logout");
    }

    onMounted(async () => {
      const parsed = parseFormUrl();
      if (!parsed?.entitySlug) return;
      const match = entities.value.find(
        (e) => e.name.toLowerCase() === parsed.entitySlug.toLowerCase(),
      );
      if (!match) return;
      initializing = true;
      selectedEntityName.value = match.name;
      await nextTick();
      initializing = false;
      if (parsed.action === "new") {
        startNew();
      } else if (parsed.action) {
        qidInput.value = parsed.action;
        await load();
      }
    });

    return {
      entities,
      selectedEntityName,
      selectedEntity,
      simpleFields,
      statementFields,
      qidInput,
      loadedData,
      pendingData,
      isNew,
      loadError,
      loadLoading,
      success,
      commitOpen,
      loadedQid,
      pendingCount,
      hasChanges,
      isValidQid,
      load,
      startNew,
      setCalendar,
      onSaved,
      logout,
      pendingStatements,
      clearSignal,
      onPendingChange,
      t,
      locale,
      setLocale,
      LANGUAGES,
    };
  },
  template: `
    <div class="app-shell">
      <header class="app-bar">
        <span class="app-bar-title">{{ t('nav_title') }}</span>
        <div class="app-bar-actions">
          <select :value="locale" @change="setLocale($event.target.value)">
            <option v-for="(label, code) in LANGUAGES" :key="code" :value="code">{{ label }}</option>
          </select>
          <button class="commit-btn" :disabled="!hasChanges" @click="commitOpen = true"
                  :title="hasChanges ? t('entity_commit_button') : t('commit_no_changes')">
            <icon name="check" />
            <span>{{ t('entity_commit_button') }}</span>
            <span v-if="pendingCount > 0" class="changes-badge">{{ pendingCount }}</span>
          </button>
          <button class="icon-btn" :title="t('nav_logout')" @click="logout">
            <icon name="logout" />
            <span v-if="username">{{ username }}</span>
          </button>
        </div>
      </header>

      <main class="editor-layout">
        <aside class="rail">
          <div class="rail-field">
            <label>{{ t('entity_type_label') }}</label>
            <select v-model="selectedEntityName">
              <option value="">{{ t('entity_type_placeholder') }}</option>
              <option v-for="e in entities" :key="e.name" :value="e.name">{{ e.name }}</option>
            </select>
          </div>

          <div class="rail-field">
            <label>{{ t('entity_load_label') }}</label>
            <item-search-input
              v-model="qidInput"
              :disabled="!selectedEntity"
            />
            <button @click="load" :aria-busy="loadLoading" :disabled="!selectedEntity || !isValidQid" style="margin-top: 0.4rem;">
              {{ t('entity_load_button') }}
            </button>
          </div>

          <button class="secondary outline" :disabled="!selectedEntity" @click="startNew">
            {{ t('entity_new_button') }}
          </button>
        </aside>

        <section class="main-pane">
          <div v-if="loadError" class="error-banner">{{ loadError }}</div>
          <div v-if="success" class="success-banner">{{ success }}</div>

          <template v-if="selectedEntity && (isNew || loadedData)">
            <h3>{{ isNew ? t('entity_new_heading', { name: selectedEntity.name }) : t('entity_loaded_heading', { name: selectedEntity.name, qid: loadedQid }) }}</h3>

            <div v-if="simpleFields.length" class="card">
              <div class="fields-grid">
                <div v-for="f in simpleFields" :key="f.name" class="field-row">
                  <label>
                    {{ f.label }}<span v-if="f.required" class="field-required">*</span>
                  </label>
                  <field-input v-if="!f.supports_references"
                               :field="f"
                               v-model="pendingData[f.name]"
                               :calendar="f.calendar_field ? pendingData[f.calendar_field] : null"
                               @update:calendar="setCalendar(f, $event)" />
                  <field-input v-else
                               :field="f"
                               v-model="pendingData[f.name]"
                               v-model:sources="pendingData[f.name + '_sources']"
                               :calendar="f.calendar_field ? pendingData[f.calendar_field] : null"
                               @update:calendar="setCalendar(f, $event)" />
                </div>
              </div>
            </div>

            <section v-for="f in statementFields" :key="f.name" class="card statement-section">
              <statement-list-editor
                :field="f"
                :parent-qid="loadedQid"
                :clear-signal="clearSignal"
                @update:pending="(name, ops, fc) => onPendingChange(name, ops, fc)"
              />
            </section>
          </template>

          <p v-else-if="selectedEntity && !isNew && !loadedData" class="entity-empty">
            {{ t('entity_empty_hint') }}
          </p>
        </section>
      </main>

      <commit-dialog
        :open="commitOpen"
        :pending-data="pendingData"
        :loaded-data="loadedData"
        :is-new="isNew"
        :entity-config="selectedEntity ?? {}"
        :pending-statements="pendingStatements"
        @close="commitOpen = false"
        @saved="onSaved"
      />
    </div>
  `,
};
