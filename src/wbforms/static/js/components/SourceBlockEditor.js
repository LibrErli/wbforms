import { useI18n } from "../i18n.js";

// `FieldInput` is registered globally in app.js so it can be referenced here as
// `<field-input>` without a static import — that import would create a circular
// dependency with FieldInput.js, which imports this component.
export default {
  name: "SourceBlockEditor",
  props: {
    referenceFields: { type: Array, required: true },
    modelValue: { type: Array, default: () => [] },
    summaryLabel: { type: String, default: "" },
  },
  emits: ["update:modelValue"],
  setup(props, { emit }) {
    const { t } = useI18n();

    function emptyBlock() {
      const block = {};
      (props.referenceFields || []).forEach((rf) => {
        block[rf.name] = rf.field_type === "list" ? [] : "";
        if (rf.calendar_field) {
          block[rf.calendar_field] = rf.field_type === "list" ? [] : "";
        }
      });
      return block;
    }

    function addBlock() {
      emit("update:modelValue", [...(props.modelValue || []), emptyBlock()]);
    }

    function removeBlock(idx) {
      const next = [...(props.modelValue || [])];
      next.splice(idx, 1);
      emit("update:modelValue", next);
    }

    function updateField(idx, name, value) {
      const next = [...(props.modelValue || [])];
      next[idx] = { ...next[idx], [name]: value };
      emit("update:modelValue", next);
    }

    return { t, addBlock, removeBlock, updateField };
  },
  template: `
    <details class="sources-section">
      <summary>
        {{ summaryLabel || t('stmt_sources_section') }}
        <span v-if="modelValue?.length" style="color:var(--muted-color)">({{ modelValue.length }})</span>
      </summary>
      <div v-for="(src, idx) in (modelValue || [])" :key="idx" class="source-block">
        <button class="icon-btn danger source-remove" type="button" :title="t('stmt_remove_source')"
                @click="removeBlock(idx)">
          <icon name="trash" />
        </button>
        <div v-for="rf in referenceFields" :key="rf.name" class="field-row">
          <label>{{ rf.label }}</label>
          <field-input :field="rf" :model-value="src[rf.name]"
                       :calendar="rf.calendar_field ? src[rf.calendar_field] : null"
                       @update:model-value="updateField(idx, rf.name, $event)"
                       @update:calendar="updateField(idx, rf.calendar_field, $event)" />
        </div>
      </div>
      <button class="link-btn" type="button" @click="addBlock">
        <icon name="plus" /> {{ t('stmt_add_source') }}
      </button>
    </details>
  `,
};
