import { useI18n } from "../i18n.js";

// Wikibase time strings are of the form `±YYYY-MM-DDTHH:MM:SSZ`. Zeros in the
// month/day slots encode lower precisions (e.g. `+2020-00-00T00:00:00Z` means
// year precision; `+2020-05-00T00:00:00Z` means month precision). The native
// date picker can only represent concrete day-precision values, so we fall back
// to a free-text custom mode whenever the value carries a zero month or day.
// Day is the finest precision currently supported by WikibaseIntegrator, so
// the picker stores a midnight time component.

const WB_TIME_RE = /^([+-])(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})Z$/;

function parseWbTime(str) {
  if (typeof str !== "string") return null;
  const m = str.match(WB_TIME_RE);
  if (!m) return null;
  return {
    sign: m[1],
    year: m[2],
    month: m[3],
    day: m[4],
    hour: m[5],
    min: m[6],
    sec: m[7],
  };
}

function canUsePicker(parsed) {
  if (!parsed) return true;
  return parsed.month !== "00" && parsed.day !== "00";
}

function toPickerString(parsed) {
  if (!parsed) return "";
  return `${parsed.year}-${parsed.month}-${parsed.day}`;
}

function fromPickerString(str) {
  if (!str) return "";
  return `+${str}T00:00:00Z`;
}

export default {
  name: "DateTimeInput",
  props: {
    modelValue: { type: String, default: "" },
    // Calendar model IRI stored for this value; "" means "not set — use the default".
    calendar: { type: String, default: "" },
    // Schema-declared default for this field; values deviating from it are flagged.
    defaultCalendar: { type: String, default: "" },
    // [{ qid, iri, label_key }] as served by /api/schema/entities.
    calendarOptions: { type: Array, default: () => [] },
  },
  emits: ["update:modelValue", "update:calendar"],
  setup(props, { emit }) {
    const { ref, computed, watch } = Vue;
    const { t } = useI18n();

    const showCalendar = computed(() => props.calendarOptions.length > 0);

    // An unset calendar means the schema default will be applied on write.
    const effectiveCalendar = computed(
      () => props.calendar || props.defaultCalendar || "",
    );

    const calendarDeviates = computed(
      () =>
        showCalendar.value &&
        !!props.defaultCalendar &&
        !!effectiveCalendar.value &&
        effectiveCalendar.value !== props.defaultCalendar,
    );

    function calendarLabel(option) {
      return option.label_key ? t(option.label_key) : option.qid;
    }

    function onCalendarInput(e) {
      emit("update:calendar", e.target.value);
    }

    const initialParsed = parseWbTime(props.modelValue);
    const customMode = ref(
      props.modelValue !== "" && !canUsePicker(initialParsed),
    );

    const pickerValue = computed(() =>
      toPickerString(parseWbTime(props.modelValue)),
    );

    const customValue = computed({
      get: () => props.modelValue ?? "",
      set: (v) => emit("update:modelValue", v),
    });

    function onPickerInput(e) {
      emit("update:modelValue", fromPickerString(e.target.value));
    }

    function toggleMode() {
      // If switching from custom → picker and the current value cannot be
      // represented by the picker, fall back to clearing rather than silently
      // dropping data: the user must confirm by clearing the field first.
      if (
        customMode.value &&
        props.modelValue &&
        !canUsePicker(parseWbTime(props.modelValue))
      ) {
        return;
      }
      customMode.value = !customMode.value;
    }

    // If an external change (e.g. loading a different entity) brings in a
    // value the picker can't display, auto-switch to custom mode.
    watch(
      () => props.modelValue,
      (v) => {
        if (v && !canUsePicker(parseWbTime(v))) {
          customMode.value = true;
        }
      },
    );

    const invalidCustom = computed(
      () =>
        customMode.value &&
        customValue.value !== "" &&
        parseWbTime(customValue.value) === null,
    );

    const toggleDisabled = computed(
      () =>
        customMode.value &&
        !!props.modelValue &&
        !canUsePicker(parseWbTime(props.modelValue)),
    );

    return {
      customMode,
      pickerValue,
      customValue,
      onPickerInput,
      toggleMode,
      invalidCustom,
      toggleDisabled,
      showCalendar,
      effectiveCalendar,
      calendarDeviates,
      calendarLabel,
      onCalendarInput,
      t,
    };
  },
  template: `
    <div class="datetime-input">
      <div class="datetime-input-row">
        <input v-if="customMode"
               type="text"
               v-model="customValue"
               placeholder="+YYYY-MM-DDTHH:MM:SSZ" />
        <input v-else
               type="date"
               :value="pickerValue"
               @input="onPickerInput" />
        <button class="icon-btn"
                type="button"
                :title="customMode ? t('datetime_use_picker') : t('datetime_use_custom')"
                :disabled="toggleDisabled"
                @click.prevent="toggleMode">
          <icon :name="customMode ? 'calendar' : 'pencil'" />
        </button>
        <select v-if="showCalendar"
                class="datetime-calendar"
                :value="effectiveCalendar"
                :title="t('calendar_label')"
                :aria-label="t('calendar_label')"
                @change="onCalendarInput">
          <option v-for="opt in calendarOptions" :key="opt.iri" :value="opt.iri">
            {{ calendarLabel(opt) }}
          </option>
        </select>
      </div>
      <small v-if="customMode" class="datetime-hint">{{ t('datetime_format_hint') }}</small>
      <small v-if="invalidCustom" class="datetime-hint datetime-hint--warn">{{ t('datetime_invalid_format') }}</small>
      <small v-if="calendarDeviates" class="datetime-hint datetime-hint--warn">
        {{ t('calendar_non_default_warning') }}
      </small>
    </div>
  `,
};
