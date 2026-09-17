import { apiFetch } from "../api.js";
import { useI18n } from "../i18n.js";
import { getLabel } from "../labelCache.js";
import FieldInput from "./FieldInput.js";
import SourceBlockEditor from "./SourceBlockEditor.js";

let _nextId = 0;

export default {
  name: "StatementListEditor",
  components: { FieldInput, SourceBlockEditor },
  emits: ["update:pending"],
  props: {
    field: { type: Object, required: true },
    parentQid: { type: String, default: null },
    clearSignal: { type: Number, default: 0 },
  },
  setup(props, { emit }) {
    const { ref, reactive, watch, computed, nextTick } = Vue;
    const { t } = useI18n();

    const rows = ref([]);
    const loading = ref(false);
    const error = ref("");
    const labelMap = reactive({});

    const pendingOps = ref([]);

    // Inline editor state. `editingKey` identifies which row the inline form
    // is attached to: "new" for a fresh add-row at the top, a `_id` for a
    // pending add/edit op already in the queue, or a `statement_id` for an
    // existing row pulled from the server. Only one open at a time.
    const editingKey = ref(null);
    const editingRow = ref(null);
    const formData = reactive({});
    const editorError = ref("");
    const deleteConfirm = ref(null);

    // Snak-type dropdown state (for enforce_unknown_stmt_name statement types)
    const snakType = ref("unknown_value");

    const pendingDeleteIds = computed(
      () =>
        new Set(
          pendingOps.value
            .filter((op) => op.type === "delete")
            .map((op) => op.statementId),
        ),
    );
    const pendingEditMap = computed(() =>
      Object.fromEntries(
        pendingOps.value
          .filter((op) => op.type === "edit")
          .map((op) => [op.statementId, op]),
      ),
    );
    const pendingAdds = computed(() =>
      pendingOps.value.filter((op) => op.type === "add"),
    );

    const subjectField = computed(() =>
      props.field.statement_fields.find((f) => f.is_subject),
    );
    const enforceUnknownStmtName = computed(
      () => !!props.field.enforce_unknown_stmt_name,
    );

    function snakTypeFromValue(v) {
      if (v === "somevalue") return "unknown_value";
      if (v === "novalue") return "no_value";
      return "value";
    }

    watch(snakType, (type) => {
      if (!subjectField.value) return;
      const name = subjectField.value.name;
      if (type === "unknown_value") formData[name] = "somevalue";
      else if (type === "no_value") formData[name] = "novalue";
      else if (formData[name] === "somevalue" || formData[name] === "novalue") {
        formData[name] = "";
      }
    });

    function resolveLabelsForRow(row) {
      const itemFields = props.field.statement_fields.filter(
        (f) => f.wikibase_type === "wikibase-item",
      );
      for (const f of itemFields) {
        const qid = row[f.name];
        if (qid && !(qid in labelMap)) {
          getLabel(qid).then((label) => {
            if (label) labelMap[qid] = label;
          });
        }
      }
    }

    function resolveRowLabels() {
      for (const row of rows.value) resolveLabelsForRow(row);
    }

    function endpointFor(parentQid) {
      if (!props.field.statement_endpoint || !parentQid) return null;
      return props.field.statement_endpoint.replace(/\{[^}]+\}/, parentQid);
    }

    async function load() {
      const url = endpointFor(props.parentQid);
      if (!url) return;
      loading.value = true;
      error.value = "";
      try {
        rows.value = (await apiFetch(url)) || [];
        resolveRowLabels();
      } catch (e) {
        error.value = e.message;
      } finally {
        loading.value = false;
      }
    }

    watch(() => props.parentQid, load, { immediate: true });
    watch(
      () => props.clearSignal,
      () => {
        pendingOps.value = [];
        closeInline();
        load();
      },
    );

    // Sources (Wikibase reference blocks) helpers
    function emptySource() {
      const block = {};
      (props.field.reference_fields || []).forEach((rf) => {
        block[rf.name] = rf.field_type === "list" ? [] : "";
        if (rf.calendar_field) {
          block[rf.calendar_field] = rf.field_type === "list" ? [] : "";
        }
      });
      return block;
    }

    function setStmtCalendar(f, value) {
      if (!f.calendar_field) return;
      formData[f.calendar_field] = value;
    }

    function cloneSources(srcArr) {
      if (!Array.isArray(srcArr)) return [];
      return srcArr.map((s) => ({ ...emptySource(), ...s }));
    }

    function sourceBlockHasValue(block) {
      return (props.field.reference_fields || []).some((rf) => {
        const v = block?.[rf.name];
        if (Array.isArray(v)) return v.some((x) => x !== "" && x != null);
        return v !== "" && v != null;
      });
    }

    function effectiveSources(row) {
      if (!row) return [];
      const sid = row.statement_id;
      const edit = sid ? pendingEditMap.value[sid] : null;
      const eff = edit?.displayRow ?? row.displayRow ?? row;
      return Array.isArray(eff?.sources) ? eff.sources : [];
    }

    // Inline editor open/close
    function focusFirstInput() {
      nextTick(() => {
        const el = document.querySelector(
          ".stmt-inline-editor input, .stmt-inline-editor select",
        );
        if (el) el.focus();
      });
    }

    function openNewInline() {
      // Populate form state BEFORE flipping editingKey: editingKey drives the v-if that mounts the
      // editor (and its ItemSearchInput children), which read formData at creation time.
      Object.keys(formData).forEach((k) => {
        delete formData[k];
      });
      props.field.statement_fields.forEach((f) => {
        formData[f.name] = f.field_type === "list" ? [] : "";
        if (f.calendar_field) {
          formData[f.calendar_field] = f.field_type === "list" ? [] : "";
        }
      });
      formData.sources = [];
      snakType.value = "unknown_value";
      if (subjectField.value) formData[subjectField.value.name] = "somevalue";
      editorError.value = "";
      editingRow.value = null;
      editingKey.value = "new";
      focusFirstInput();
    }

    function rowKey(row) {
      if (row?._id !== undefined) return `op-${row._id}`;
      if (row?.statement_id) return `sid-${row.statement_id}`;
      return null;
    }

    function openEditInline(row) {
      const src =
        row._id !== undefined
          ? row.data
          : (pendingEditMap.value[row.statement_id]?.data ?? row);
      const nextRow =
        row._id !== undefined
          ? row
          : (pendingEditMap.value[row.statement_id] ?? row);

      // Populate form state BEFORE flipping editingKey: editingKey drives the v-if that mounts the
      // editor (and its ItemSearchInput children), which read formData at creation time. Mounting
      // first would leave item fields/labels empty until a later prop change (the "second click" bug).
      Object.keys(formData).forEach((k) => {
        delete formData[k];
      });
      props.field.statement_fields.forEach((f) => {
        formData[f.name] = src[f.name] ?? (f.field_type === "list" ? [] : "");
        if (f.calendar_field) {
          formData[f.calendar_field] =
            src[f.calendar_field] ?? (f.field_type === "list" ? [] : "");
        }
      });
      formData.sources = cloneSources(src.sources);
      if (subjectField.value && enforceUnknownStmtName.value) {
        snakType.value = snakTypeFromValue(src[subjectField.value.name] ?? "");
      }
      editorError.value = "";
      editingRow.value = nextRow;
      editingKey.value = rowKey(nextRow) ?? rowKey(row);
      focusFirstInput();
    }

    function closeInline() {
      editingKey.value = null;
      editingRow.value = null;
      editorError.value = "";
    }

    function saveInline() {
      const body = { ...formData };
      props.field.statement_fields.forEach((f) => {
        if (f.field_type === "list" && Array.isArray(body[f.name])) {
          body[f.name] = body[f.name].filter((v) => v !== "" && v != null);
        }
      });
      if (props.field.supports_references) {
        body.sources = (formData.sources || []).filter(sourceBlockHasValue);
      } else {
        delete body.sources;
      }

      // New statements are validated against the strict Create model on commit, so an
      // add-row missing a mandatory field would be rejected there anyway — surface it
      // here instead. Edits of existing statements may stay incomplete (the commit
      // dialog asks for confirmation).
      const opType =
        editingRow.value == null
          ? "add"
          : editingRow.value._id !== undefined
            ? (pendingOps.value.find((op) => op._id === editingRow.value._id)
                ?.type ?? "add")
            : "edit";
      if (opType === "add") {
        const missing = props.field.statement_fields
          .filter((f) => {
            if (!f.required) return false;
            const v = body[f.name];
            return v == null || v === "" || (Array.isArray(v) && !v.length);
          })
          .map((f) => f.label);
        if (missing.length) {
          editorError.value = t("stmt_missing_required", {
            fields: missing.join(", "),
          });
          return;
        }
      }

      if (editingRow.value) {
        if (editingRow.value._id !== undefined) {
          const idx = pendingOps.value.findIndex(
            (op) => op._id === editingRow.value._id,
          );
          if (idx >= 0) {
            pendingOps.value.splice(idx, 1, {
              ...pendingOps.value[idx],
              data: body,
              displayRow: body,
            });
          }
        } else {
          const sid = editingRow.value.statement_id;
          const existingIdx = pendingOps.value.findIndex(
            (op) => op.type === "edit" && op.statementId === sid,
          );
          if (existingIdx >= 0) {
            pendingOps.value.splice(existingIdx, 1, {
              ...pendingOps.value[existingIdx],
              data: body,
              displayRow: body,
            });
          } else {
            pendingOps.value.push({
              _id: ++_nextId,
              type: "edit",
              statementId: sid,
              data: body,
              displayRow: body,
            });
          }
        }
      } else {
        pendingOps.value.push({
          _id: ++_nextId,
          type: "add",
          data: body,
          displayRow: body,
        });
      }

      resolveLabelsForRow(body);
      closeInline();
      emit("update:pending", props.field.name, pendingOps.value, props.field);
    }

    function markDelete(row) {
      if (row._id !== undefined) {
        pendingOps.value = pendingOps.value.filter((op) => op._id !== row._id);
      } else {
        pendingOps.value.push({
          _id: ++_nextId,
          type: "delete",
          statementId: row.statement_id,
          displayRow: row,
        });
      }
      deleteConfirm.value = null;
      emit("update:pending", props.field.name, pendingOps.value, props.field);
    }

    function undoOp(opId) {
      pendingOps.value = pendingOps.value.filter((op) => op._id !== opId);
      emit("update:pending", props.field.name, pendingOps.value, props.field);
    }

    function displayValue(row, f) {
      const v = row[f.name];
      if (v == null || v === "") return "—";
      if (Array.isArray(v)) return v.join(", ") || "—";
      if (f.is_subject) {
        if (v === "somevalue") return t("stmt_display_unknown");
        if (v === "novalue") return t("stmt_display_no_value");
      }
      if (f.wikibase_type === "wikibase-item")
        return labelMap[v] ? `${labelMap[v]} (${v})` : v;
      return String(v);
    }

    const visibleCols = computed(() => props.field.statement_fields);
    const colSpan = computed(() => visibleCols.value.length + 1);

    function isEditingRow(row) {
      return editingKey.value !== null && editingKey.value === rowKey(row);
    }

    return {
      rows,
      loading,
      error,
      labelMap,
      pendingOps,
      pendingDeleteIds,
      pendingEditMap,
      pendingAdds,
      editingKey,
      editingRow,
      formData,
      editorError,
      deleteConfirm,
      openNewInline,
      openEditInline,
      closeInline,
      saveInline,
      markDelete,
      undoOp,
      displayValue,
      visibleCols,
      colSpan,
      snakType,
      subjectField,
      enforceUnknownStmtName,
      effectiveSources,
      isEditingRow,
      setStmtCalendar,
      t,
    };
  },
  template: `
    <div>
      <div class="card-header">
        <h4>{{ field.label }}</h4>
        <button class="link-btn" @click="openNewInline" :disabled="editingKey === 'new'">
          <icon name="plus" /> {{ t('stmt_add_button', { label: field.label }) }}
        </button>
      </div>

      <div v-if="error" class="error-banner">{{ error }}</div>

      <div v-if="loading">
        <span class="spinner"></span> {{ t('stmt_loading') }}
      </div>

      <table v-else-if="rows.length || pendingAdds.length || editingKey === 'new'" class="stmt-table">
        <thead>
          <tr>
            <th v-for="f in visibleCols" :key="f.name">{{ f.label }}</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          <!-- Inline editor for a fresh "add" row -->
          <tr v-if="editingKey === 'new'" class="stmt-inline-editor">
            <td :colspan="colSpan">
              <div class="inline-editor-body">
                <template v-for="f in field.statement_fields" :key="f.name">
                  <template v-if="f.is_subject && enforceUnknownStmtName">
                    <div class="field-row">
                      <label>{{ t('stmt_snak_type') }}</label>
                      <select v-model="snakType">
                        <option value="value">{{ t('stmt_snak_value') }}</option>
                        <option value="unknown_value">{{ t('stmt_snak_unknown') }}</option>
                        <option value="no_value">{{ t('stmt_snak_no_value') }}</option>
                      </select>
                    </div>
                    <div v-if="snakType === 'value'" class="field-row">
                      <label>{{ f.label }}<span class="field-required">*</span></label>
                      <field-input :field="f" v-model="formData[f.name]"
                                   :calendar="f.calendar_field ? formData[f.calendar_field] : null"
                                   @update:calendar="setStmtCalendar(f, $event)" />
                    </div>
                  </template>
                  <template v-else-if="f.is_object_named_as && enforceUnknownStmtName">
                    <div v-if="snakType === 'unknown_value'" class="field-row">
                      <label>{{ f.label }}<span class="field-required">*</span></label>
                      <field-input :field="f" v-model="formData[f.name]"
                                   :calendar="f.calendar_field ? formData[f.calendar_field] : null"
                                   @update:calendar="setStmtCalendar(f, $event)" />
                    </div>
                  </template>
                  <div v-else class="field-row">
                    <label>
                      {{ f.label }}<span v-if="f.required" class="field-required">*</span>
                    </label>
                    <field-input :field="f" v-model="formData[f.name]"
                                 :calendar="f.calendar_field ? formData[f.calendar_field] : null"
                                 @update:calendar="setStmtCalendar(f, $event)" />
                  </div>
                </template>
                <div v-if="field.supports_references" class="inline-editor-sources">
                  <source-block-editor :reference-fields="field.reference_fields"
                                       v-model="formData.sources" />
                </div>
                <div v-if="editorError" class="error-banner inline-editor-sources">{{ editorError }}</div>
                <div class="inline-editor-footer">
                  <button class="secondary outline" type="button" @click="closeInline">
                    {{ t('stmt_cancel_button') }}
                  </button>
                  <button type="button" @click="saveInline">
                    {{ t('stmt_save_button') }}
                  </button>
                </div>
              </div>
            </td>
          </tr>

          <!-- Saved rows + per-row inline editor -->
          <template v-for="row in rows" :key="row.statement_id">
            <tr :class="pendingDeleteIds.has(row.statement_id) ? 'stmt-row--deleted' : ''">
              <td v-for="f in visibleCols" :key="f.name">
                {{ displayValue(pendingEditMap[row.statement_id]?.displayRow ?? row, f) }}
              </td>
              <td>
                <div class="stmt-row-actions">
                  <template v-if="pendingDeleteIds.has(row.statement_id)">
                    <button class="icon-btn" :title="t('stmt_undo_button')"
                            @click="undoOp(pendingOps.find(op=>op.statementId===row.statement_id)?._id)">
                      <icon name="undo" />
                    </button>
                  </template>
                  <template v-else>
                    <button class="icon-btn" :title="t('stmt_edit_button')" @click="openEditInline(row)">
                      <icon name="pencil" />
                    </button>
                    <span v-if="effectiveSources(row).length" class="stmt-meta"
                          :title="t('stmt_source_count', { count: effectiveSources(row).length })">
                      <icon name="book" /> {{ effectiveSources(row).length }}
                    </span>
                    <span v-if="pendingEditMap[row.statement_id]" class="stmt-meta text-warning"
                          :title="t('stmt_pending')">
                      <icon name="warning" />
                    </span>
                    <template v-if="deleteConfirm === row">
                      <small>{{ t('stmt_delete_confirm') }}</small>
                      <button @click="markDelete(row)" style="padding:0.2rem 0.5rem">{{ t('stmt_delete_yes') }}</button>
                      <button class="secondary outline" @click="deleteConfirm=null" style="padding:0.2rem 0.5rem">
                        {{ t('stmt_delete_no') }}
                      </button>
                    </template>
                    <button v-else class="icon-btn danger" :title="t('stmt_remove_button')"
                            @click="deleteConfirm=row">
                      <icon name="trash" />
                    </button>
                  </template>
                </div>
              </td>
            </tr>
            <tr v-if="isEditingRow(row) || isEditingRow(pendingEditMap[row.statement_id])"
                class="stmt-inline-editor">
              <td :colspan="colSpan">
                <div class="inline-editor-body">
                  <template v-for="f in field.statement_fields" :key="f.name">
                    <template v-if="f.is_subject && enforceUnknownStmtName">
                      <div class="field-row">
                        <label>{{ t('stmt_snak_type') }}</label>
                        <select v-model="snakType">
                          <option value="value">{{ t('stmt_snak_value') }}</option>
                          <option value="unknown_value">{{ t('stmt_snak_unknown') }}</option>
                          <option value="no_value">{{ t('stmt_snak_no_value') }}</option>
                        </select>
                      </div>
                      <div v-if="snakType === 'value'" class="field-row">
                        <label>{{ f.label }}<span class="field-required">*</span></label>
                        <field-input :field="f" v-model="formData[f.name]"
                                     :calendar="f.calendar_field ? formData[f.calendar_field] : null"
                                     @update:calendar="setStmtCalendar(f, $event)" />
                      </div>
                    </template>
                    <template v-else-if="f.is_object_named_as && enforceUnknownStmtName">
                      <div v-if="snakType === 'unknown_value'" class="field-row">
                        <label>{{ f.label }}<span class="field-required">*</span></label>
                        <field-input :field="f" v-model="formData[f.name]"
                                     :calendar="f.calendar_field ? formData[f.calendar_field] : null"
                                     @update:calendar="setStmtCalendar(f, $event)" />
                      </div>
                    </template>
                    <div v-else class="field-row">
                      <label>
                        {{ f.label }}<span v-if="f.required" class="field-required">*</span>
                      </label>
                      <field-input :field="f" v-model="formData[f.name]"
                                   :calendar="f.calendar_field ? formData[f.calendar_field] : null"
                                   @update:calendar="setStmtCalendar(f, $event)" />
                    </div>
                  </template>
                  <div v-if="field.supports_references" class="inline-editor-sources">
                    <source-block-editor :reference-fields="field.reference_fields"
                                         v-model="formData.sources" />
                  </div>
                  <div v-if="editorError" class="error-banner inline-editor-sources">{{ editorError }}</div>
                  <div class="inline-editor-footer">
                    <button class="secondary outline" type="button" @click="closeInline">
                      {{ t('stmt_cancel_button') }}
                    </button>
                    <button type="button" @click="saveInline">
                      {{ t('stmt_save_button') }}
                    </button>
                  </div>
                </div>
              </td>
            </tr>
          </template>

          <!-- Pending add rows (queued, not yet committed) -->
          <template v-for="op in pendingAdds" :key="op._id">
            <tr class="stmt-row--pending">
              <td v-for="f in visibleCols" :key="f.name">{{ displayValue(op.displayRow, f) }}</td>
              <td>
                <div class="stmt-row-actions">
                  <button class="icon-btn" :title="t('stmt_edit_button')" @click="openEditInline(op)">
                    <icon name="pencil" />
                  </button>
                  <button class="icon-btn danger" :title="t('stmt_remove_button')" @click="undoOp(op._id)">
                    <icon name="trash" />
                  </button>
                  <span v-if="op.displayRow?.sources?.length" class="stmt-meta"
                        :title="t('stmt_source_count', { count: op.displayRow.sources.length })">
                    <icon name="book" /> {{ op.displayRow.sources.length }}
                  </span>
                  <span class="stmt-meta text-warning" :title="t('stmt_pending')">
                    <icon name="warning" /> {{ t('stmt_pending') }}
                  </span>
                </div>
              </td>
            </tr>
            <tr v-if="isEditingRow(op)" class="stmt-inline-editor">
              <td :colspan="colSpan">
                <div class="inline-editor-body">
                  <template v-for="f in field.statement_fields" :key="f.name">
                    <template v-if="f.is_subject && enforceUnknownStmtName">
                      <div class="field-row">
                        <label>{{ t('stmt_snak_type') }}</label>
                        <select v-model="snakType">
                          <option value="value">{{ t('stmt_snak_value') }}</option>
                          <option value="unknown_value">{{ t('stmt_snak_unknown') }}</option>
                          <option value="no_value">{{ t('stmt_snak_no_value') }}</option>
                        </select>
                      </div>
                      <div v-if="snakType === 'value'" class="field-row">
                        <label>{{ f.label }}<span class="field-required">*</span></label>
                        <field-input :field="f" v-model="formData[f.name]"
                                     :calendar="f.calendar_field ? formData[f.calendar_field] : null"
                                     @update:calendar="setStmtCalendar(f, $event)" />
                      </div>
                    </template>
                    <template v-else-if="f.is_object_named_as && enforceUnknownStmtName">
                      <div v-if="snakType === 'unknown_value'" class="field-row">
                        <label>{{ f.label }}<span class="field-required">*</span></label>
                        <field-input :field="f" v-model="formData[f.name]"
                                     :calendar="f.calendar_field ? formData[f.calendar_field] : null"
                                     @update:calendar="setStmtCalendar(f, $event)" />
                      </div>
                    </template>
                    <div v-else class="field-row">
                      <label>
                        {{ f.label }}<span v-if="f.required" class="field-required">*</span>
                      </label>
                      <field-input :field="f" v-model="formData[f.name]"
                                   :calendar="f.calendar_field ? formData[f.calendar_field] : null"
                                   @update:calendar="setStmtCalendar(f, $event)" />
                    </div>
                  </template>
                  <div v-if="field.supports_references" class="inline-editor-sources">
                    <source-block-editor :reference-fields="field.reference_fields"
                                         v-model="formData.sources" />
                  </div>
                  <div v-if="editorError" class="error-banner inline-editor-sources">{{ editorError }}</div>
                  <div class="inline-editor-footer">
                    <button class="secondary outline" type="button" @click="closeInline">
                      {{ t('stmt_cancel_button') }}
                    </button>
                    <button type="button" @click="saveInline">
                      {{ t('stmt_save_button') }}
                    </button>
                  </div>
                </div>
              </td>
            </tr>
          </template>
        </tbody>
      </table>

      <p v-else class="stmt-empty">{{ t('stmt_empty') }}</p>
    </div>
  `,
};
