import { useI18n } from "../i18n.js";
import DateTimeInput from "./DateTimeInput.js";
import ItemSearchInput from "./ItemSearchInput.js";
import SourceBlockEditor from "./SourceBlockEditor.js";

export default {
  name: "FieldInput",
  components: { DateTimeInput, ItemSearchInput, SourceBlockEditor },
  props: {
    field: { type: Object, required: true },
    modelValue: { default: null },
    // Single-valued field: list[block]. Multivalued field: list[list[block]] (positional with modelValue).
    sources: { default: null },
    // Time fields only. Single-valued: a calendar model IRI. Multivalued: a positional list of them.
    calendar: { default: null },
  },
  emits: ["update:modelValue", "update:sources", "update:calendar"],
  setup(props, { emit }) {
    const { computed } = Vue;
    const { t } = useI18n();

    const isItem = computed(
      () => props.field.wikibase_type === "wikibase-item",
    );
    const isNumber = computed(() => props.field.wikibase_type === "quantity");
    const isUrl = computed(() => props.field.wikibase_type === "url");
    const isTime = computed(() => props.field.wikibase_type === "time");
    const isList = computed(() => props.field.field_type === "list");
    const supportsRefs = computed(() => !!props.field.supports_references);

    const inputType = computed(() => {
      if (isNumber.value) return "number";
      if (isUrl.value) return "url";
      return "text";
    });

    const listVal = computed(() => {
      if (!isList.value) return [];
      return Array.isArray(props.modelValue)
        ? props.modelValue
        : props.modelValue
          ? [props.modelValue]
          : [""];
    });

    const singleSources = computed(() =>
      Array.isArray(props.sources) ? props.sources : [],
    );

    function updateList(idx, newVal) {
      const arr = [...listVal.value];
      arr[idx] = newVal;
      emit("update:modelValue", arr);
    }

    function addListItem() {
      emit("update:modelValue", [...listVal.value, ""]);
      if (supportsRefs.value) {
        const next = Array.isArray(props.sources) ? [...props.sources] : [];
        next.push([]);
        emit("update:sources", next);
      }
      if (isTime.value) {
        const next = Array.isArray(props.calendar) ? [...props.calendar] : [];
        next.push(defaultCalendar.value);
        emit("update:calendar", next);
      }
    }

    function removeListItem(idx) {
      const arr = listVal.value.filter((_, i) => i !== idx);
      emit("update:modelValue", arr.length ? arr : [""]);
      if (supportsRefs.value) {
        const next = Array.isArray(props.sources) ? [...props.sources] : [];
        next.splice(idx, 1);
        emit("update:sources", next);
      }
      if (isTime.value) {
        const next = Array.isArray(props.calendar) ? [...props.calendar] : [];
        next.splice(idx, 1);
        emit("update:calendar", next);
      }
    }

    const calendarOptions = computed(() => props.field.calendar_options || []);
    const defaultCalendar = computed(
      () => props.field.default_calendar_model || "",
    );

    const singleCalendar = computed(() =>
      typeof props.calendar === "string" ? props.calendar : "",
    );

    function calendarForIndex(idx) {
      return Array.isArray(props.calendar) ? (props.calendar[idx] ?? "") : "";
    }

    function updateCalendarForIndex(idx, value) {
      const next = Array.isArray(props.calendar) ? [...props.calendar] : [];
      // The calendar list is positional with modelValue, so pad any gap left by
      // values added before a calendar was ever chosen.
      while (next.length <= idx) next.push(defaultCalendar.value);
      next[idx] = value;
      emit("update:calendar", next);
    }

    function sourcesForIndex(idx) {
      if (!Array.isArray(props.sources)) return [];
      return Array.isArray(props.sources[idx]) ? props.sources[idx] : [];
    }

    function updateSourcesForIndex(idx, blocks) {
      const next = Array.isArray(props.sources) ? [...props.sources] : [];
      while (next.length <= idx) next.push([]);
      next[idx] = blocks;
      emit("update:sources", next);
    }

    function onSingle(e) {
      const v = e.target ? e.target.value : e;
      emit(
        "update:modelValue",
        isNumber.value ? (v === "" ? null : Number(v)) : v,
      );
    }

    return {
      isItem,
      isNumber,
      isUrl,
      isTime,
      isList,
      inputType,
      listVal,
      supportsRefs,
      singleSources,
      calendarOptions,
      defaultCalendar,
      singleCalendar,
      calendarForIndex,
      updateCalendarForIndex,
      updateList,
      addListItem,
      removeListItem,
      sourcesForIndex,
      updateSourcesForIndex,
      onSingle,
      t,
    };
  },
  template: `
    <div>
      <!-- List field -->
      <template v-if="isList">
        <div v-for="(val, idx) in listVal" :key="idx" class="list-field-item-group">
          <div class="list-field-item">
            <item-search-input
              v-if="isItem"
              :model-value="val"
              @update:model-value="updateList(idx, $event)"
            />
            <date-time-input
              v-else-if="isTime"
              :model-value="val || ''"
              :calendar="calendarForIndex(idx)"
              :default-calendar="defaultCalendar"
              :calendar-options="calendarOptions"
              @update:model-value="updateList(idx, $event)"
              @update:calendar="updateCalendarForIndex(idx, $event)"
            />
            <input
              v-else
              :type="inputType"
              :value="val"
              @input="updateList(idx, $event.target.value)"
            />
            <button class="icon-btn danger" type="button" :title="t('stmt_remove_button')"
                    @click.prevent="removeListItem(idx)">
              <icon name="x" />
            </button>
          </div>
          <source-block-editor v-if="supportsRefs"
                               :reference-fields="field.reference_fields"
                               :model-value="sourcesForIndex(idx)"
                               @update:model-value="updateSourcesForIndex(idx, $event)" />
        </div>
        <button class="link-btn" type="button" @click.prevent="addListItem">
          <icon name="plus" /> {{ t('field_add_item') }}
        </button>
      </template>

      <!-- Single item field -->
      <template v-else>
        <item-search-input
          v-if="isItem"
          :model-value="modelValue || ''"
          @update:model-value="$emit('update:modelValue', $event)"
        />
        <date-time-input
          v-else-if="isTime"
          :model-value="modelValue || ''"
          :calendar="singleCalendar"
          :default-calendar="defaultCalendar"
          :calendar-options="calendarOptions"
          @update:model-value="$emit('update:modelValue', $event)"
          @update:calendar="$emit('update:calendar', $event)"
        />
        <input
          v-else
          :type="inputType"
          :value="modelValue ?? ''"
          @input="onSingle"
        />
        <source-block-editor v-if="supportsRefs"
                             :reference-fields="field.reference_fields"
                             :model-value="singleSources"
                             @update:model-value="$emit('update:sources', $event)" />
      </template>
    </div>
  `,
};
