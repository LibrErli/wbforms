import { apiFetch } from "../api.js";
import { useI18n } from "../i18n.js";
import { getLabel } from "../labelCache.js";

export default {
  name: "ItemSearchInput",
  props: {
    modelValue: { type: String, default: "" },
    label: { type: String, default: "" },
  },
  emits: ["update:modelValue", "update:label"],
  setup(props, { emit }) {
    const { ref, watch, nextTick } = Vue;
    const { t } = useI18n();

    // --- Selected state ---
    const selectedQid = ref("");
    const selectedLabel = ref(props.label || "");

    // --- Search state ---
    const isSearching = ref(true);
    const searchText = ref("");
    const suggestions = ref([]);
    const activeIdx = ref(-1);
    const searchError = ref("");
    let debounceTimer = null;

    // --- Initialise from prop ---
    async function initFromQid(qid) {
      console.log(`ItemSearchInput.initFromQid - starting for qid:`, qid);
      selectedQid.value = qid;
      selectedLabel.value = "";
      isSearching.value = false;
      emit("update:label", "");
      console.log(`ItemSearchInput.initFromQid - set isSearching=false, selectedQid=`, selectedQid.value);
      const label = await getLabel(qid);
      console.log(`ItemSearchInput.initFromQid - got label for ${qid}:`, label);
      if (selectedQid.value === qid) {
        selectedLabel.value = label;
        emit("update:label", label || qid);
        console.log(`ItemSearchInput.initFromQid - set selectedLabel=`, selectedLabel.value);
      } else {
        console.log(`ItemSearchInput.initFromQid - WARNING: selectedQid changed, not setting label`);
      }
    }

    // Initialise (and re-initialise) the chip/label from the current value via an immediate watch.
    // Doing this as an effect — rather than a one-time read at creation — makes the displayed value
    // and resolved label independent of mount timing: when the inline editor mounts with its
    // model-value already set, the chip + label populate on the first open.
    watch(
      () => props.modelValue,
      (v) => {
        console.log(`ItemSearchInput watch - modelValue changed to:`, v, `current selectedQid:`, selectedQid.value);
        if (v === selectedQid.value) return;
        if (v && /^Q\d+$/i.test(v)) {
          console.log(`ItemSearchInput - calling initFromQid with:`, v);
          initFromQid(v);
        } else {
          console.log(`ItemSearchInput - clearing selection`);
          selectedQid.value = "";
          selectedLabel.value = "";
          isSearching.value = true;
          searchText.value = "";
          suggestions.value = [];
        }
      },
      { immediate: true },
    );

    // --- Mode transitions ---
    function enterSearch() {
      searchText.value = selectedLabel.value || selectedQid.value;
      suggestions.value = [];
      searchError.value = "";
      isSearching.value = true;
      // Auto-trigger search so suggestions appear immediately with the pre-filled text
      nextTick(() => {
        if (searchText.value.trim()) onSearchInput();
      });
    }

    function cancelSearch() {
      if (selectedQid.value) {
        isSearching.value = false;
      } else {
        searchText.value = "";
        suggestions.value = [];
      }
    }

    function clearSelection() {
      selectedQid.value = "";
      selectedLabel.value = "";
      isSearching.value = true;
      searchText.value = "";
      suggestions.value = [];
      emit("update:modelValue", "");
      emit("update:label", "");
    }

    function select(item) {
      selectedQid.value = item.id;
      selectedLabel.value = item.label || "";
      suggestions.value = [];
      isSearching.value = false;
      emit("update:modelValue", item.id);
      emit("update:label", item.label || item.id);
    }

    async function confirmQid(qid) {
      selectedQid.value = qid;
      selectedLabel.value = "";
      isSearching.value = false;
      suggestions.value = [];
      emit("update:modelValue", qid);
      emit("update:label", "");
      const label = await getLabel(qid);
      if (selectedQid.value === qid) {
        selectedLabel.value = label;
        emit("update:label", label || qid);
      }
    }

    // --- Search input handlers ---
    async function onSearchInput() {
      activeIdx.value = -1;
      clearTimeout(debounceTimer);
      searchError.value = "";
      const q = searchText.value.trim();
      if (!q) {
        suggestions.value = [];
        return;
      }
      debounceTimer = setTimeout(async () => {
        try {
          suggestions.value =
            (await apiFetch(
              `/api/entity-search?q=${encodeURIComponent(q)}&limit=80`,
            )) || [];
          searchError.value = "";
        } catch (e) {
          suggestions.value = [];
          searchError.value = e.message || t("search_failed");
        }
      }, 300);
    }

    function onBlur() {
      setTimeout(() => {
        const q = searchText.value.trim();
        if (q.match(/^Q\d+$/i)) {
          confirmQid(q);
        } else if (selectedQid.value) {
          isSearching.value = false;
        }
        suggestions.value = [];
      }, 150);
    }

    function onKey(e) {
      if (e.key === "Enter") {
        if (activeIdx.value >= 0 && suggestions.value[activeIdx.value]) {
          select(suggestions.value[activeIdx.value]);
          e.preventDefault();
        } else {
          const q = searchText.value.trim();
          if (q.match(/^Q\d+$/i)) {
            confirmQid(q);
            e.preventDefault();
          }
        }
        return;
      }
      if (!suggestions.value.length) return;
      if (e.key === "ArrowDown") {
        activeIdx.value = Math.min(
          activeIdx.value + 1,
          suggestions.value.length - 1,
        );
        e.preventDefault();
      } else if (e.key === "ArrowUp") {
        activeIdx.value = Math.max(activeIdx.value - 1, 0);
        e.preventDefault();
      } else if (e.key === "Escape") {
        suggestions.value = [];
        if (selectedQid.value) isSearching.value = false;
      }
    }

    return {
      selectedQid,
      selectedLabel,
      isSearching,
      searchText,
      suggestions,
      activeIdx,
      searchError,
      enterSearch,
      cancelSearch,
      clearSelection,
      select,
      onSearchInput,
      onBlur,
      onKey,
      t,
    };
  },
  template: `
    <div class="search-wrap">
      <!-- Selected mode: chip -->
      <div v-if="!isSearching && selectedQid" class="item-chip">
        <span class="item-chip-label">{{ selectedLabel || selectedQid }}</span>
        <span class="item-chip-id">({{ selectedQid }})</span>
        <div class="item-chip-actions">
          <button class="icon-btn" type="button" @click="enterSearch" :title="t('search_change')">
            <icon name="pencil" />
          </button>
          <button class="icon-btn danger" type="button" @click="clearSelection" :title="t('search_clear')">
            <icon name="trash" />
          </button>
        </div>
      </div>

      <!-- Search mode -->
      <template v-else>
        <div class="search-row">
          <input
            v-model="searchText"
            type="text"
            :placeholder="t('search_placeholder')"
            @input="onSearchInput"
            @blur="onBlur"
            @keydown="onKey"
            autocomplete="off"
          />
          <button v-if="selectedQid" class="icon-btn" type="button"
                  @click="cancelSearch" :title="t('search_cancel')">
            <icon name="x" />
          </button>
        </div>
        <div v-if="suggestions.length" class="suggestions">
          <div
            v-for="(s, i) in suggestions"
            :key="s.id"
            class="suggestion-item"
            :class="{ active: i === activeIdx }"
            @mousedown.prevent="select(s)"
          >
            <span class="suggestion-label">{{ s.label }}</span>
            <span class="suggestion-id">({{ s.id }})</span>
            <br><span class="suggestion-desc">{{ s.description }}</span>
          </div>
        </div>
        <small v-if="searchError" style="color:var(--del-color)">{{ searchError }}</small>
      </template>
    </div>
  `,
};
