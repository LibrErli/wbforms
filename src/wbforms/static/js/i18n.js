import { ref } from "vue";

const SUPPORTED = ["en", "de"];
export const LANGUAGES = { en: "English", de: "Deutsch" };
const detected = (navigator.language ?? "en").split("-")[0];
const initial =
  localStorage.getItem("locale") ||
  (SUPPORTED.includes(detected) ? detected : "en");

export const locale = ref(initial);
document.documentElement.lang = initial;

export function setLocale(lang) {
  locale.value = lang;
  localStorage.setItem("locale", lang);
  document.documentElement.lang = lang;
}

const messages = {
  en: {
    app_loading_schema: "Loading schema…",
    app_schema_error: "Failed to load schema: {error}",

    login_title:
      "Formular - Besucherbücher der kurfürstlich-königlichen Bibliothek in Dresden",
    login_subtitle: "Sign in with your Wikibase account",
    login_invalid: "Invalid credentials",
    login_username: "Username",
    login_password: "Password",
    login_submit: "Login with Wikibase",
    login_or: "or",
    login_oauth_submit: "Login via FactGrid OAuth",
    login_oauth_version: "Using OAuth {version}",

    nav_title:
      "Besucherbücher der kurfürstlich-königlichen Bibliothek in Dresden",
    nav_logout: "Logout",
    entity_type_label: "Entity type",
    entity_type_placeholder: "— Select —",
    entity_load_label: "Load existing QID",
    entity_load_placeholder: "Q…",
    entity_load_button: "Load",
    entity_new_button: "New",
    entity_commit_button: "Commit changes…",
    entity_new_heading: "New {name}",
    entity_loaded_heading: "{name} — {qid}",
    entity_empty_hint:
      "Enter a QID and click Load, or click New to create a new entity.",
    entity_saved: "Saved! QID: {qid}",

    commit_title_create: "Create {name}",
    commit_title_update: "Update {name}",
    commit_no_changes: "No changes detected.",
    commit_review: "Review changes before writing to Wikibase:",
    commit_col_field: "Field",
    commit_col_current: "Current",
    commit_col_new: "New Value",
    commit_stmt_heading: "Statement changes",
    commit_sources_heading: "Reference changes",
    commit_source_count: "{count} source(s)",
    commit_col_section: "Section",
    commit_col_action: "Action",
    commit_col_values: "Values",
    commit_op_add: "Add",
    commit_op_edit: "Edit",
    commit_op_remove: "Remove",
    commit_cancel: "Cancel",
    commit_confirm: "Confirm & Write to Wikibase",
    commit_missing_required: "Mandatory fields are still empty: {fields}",
    commit_missing_required_block:
      "Cannot write: mandatory fields are missing: {fields}",
    commit_incomplete_ack: "Write anyway — the item will remain incomplete",

    stmt_loading: "Loading…",
    stmt_empty: "No entries yet.",
    stmt_add_button: "Add {label}",
    stmt_edit_button: "Edit",
    stmt_remove_button: "Remove",
    stmt_undo_button: "Undo",
    stmt_delete_confirm: "Sure?",
    stmt_delete_yes: "Yes",
    stmt_delete_no: "No",
    stmt_pending: "pending",
    stmt_snak_type: "Snak type",
    stmt_snak_value: "Has value",
    stmt_snak_unknown: "Unknown value",
    stmt_snak_no_value: "No value",
    stmt_display_unknown: "Unknown value",
    stmt_display_no_value: "No value",
    stmt_dialog_add: "Add {label}",
    stmt_dialog_edit: "Edit {label}",
    stmt_save_button: "Save",
    stmt_cancel_button: "Cancel",
    stmt_sources_section: "Sources",
    stmt_add_source: "Add source",
    stmt_remove_source: "Remove",
    stmt_source_count: "{count} source(s) attached",
    stmt_missing_required: "Mandatory fields are missing: {fields}",

    field_add_item: "Add",

    datetime_use_picker: "Use date picker",
    datetime_use_custom: "Enter custom value",
    datetime_format_hint:
      "Format: +YYYY-MM-DDTHH:MM:SSZ — use 00 for unknown parts (e.g. +2020-00-00T00:00:00Z for year precision).",
    datetime_invalid_format:
      "Value does not match the expected Wikibase time format.",

    search_placeholder: "Search by label or enter QID…",
    search_change: "Change",
    search_cancel: "Cancel",
    search_clear: "Clear",
    search_failed: "Search failed",
    footer_impressum: "Imprint",
  },
  de: {
    app_loading_schema: "Schema wird geladen…",
    app_schema_error: "Schema konnte nicht geladen werden: {error}",

    login_title:
      "Besucherbücher der kurfürstlich-königlichen Bibliothek in Dresden",
    login_subtitle: "Mit Factgrid-Konto anmelden",
    login_invalid: "Ungültige Zugangsdaten",
    login_username: "Benutzername",
    login_password: "Passwort",
    login_submit: "Mit FactGrid anmelden",
    login_or: "oder",
    login_oauth_submit: "Über FactGrid OAuth anmelden",
    login_oauth_version: "Verwendet OAuth {version}",

    nav_title:
      "Personen in Besucherbüchern der kurfürstlich-königlichen Bibliothek in Dresden",
    nav_logout: "Abmelden",
    entity_type_label: "Entitätstyp",
    entity_type_placeholder: "— Auswählen —",
    entity_load_label: "Vorhandene QID laden",
    entity_load_placeholder: "Q…",
    entity_load_button: "Laden",
    entity_new_button: "Neu",
    entity_commit_button: "Änderungen übernehmen…",
    entity_new_heading: "Neu: {name}",
    entity_loaded_heading: "{name} — {qid}",
    entity_empty_hint:
      "QID eingeben und auf Laden klicken, oder Neu klicken, um eine neue Entität zu erstellen.",
    entity_saved: "Gespeichert! QID: {qid}",

    commit_title_create: "{name} erstellen",
    commit_title_update: "{name} aktualisieren",
    commit_no_changes: "Keine Änderungen erkannt.",
    commit_review: "Änderungen vor dem Speichern in Wikibase prüfen:",
    commit_col_field: "Feld",
    commit_col_current: "Aktuell",
    commit_col_new: "Neuer Wert",
    commit_stmt_heading: "Aussageänderungen",
    commit_sources_heading: "Quellenänderungen",
    commit_source_count: "{count} Quelle(n)",
    commit_col_section: "Bereich",
    commit_col_action: "Aktion",
    commit_col_values: "Werte",
    commit_op_add: "Hinzufügen",
    commit_op_edit: "Bearbeiten",
    commit_op_remove: "Entfernen",
    commit_cancel: "Abbrechen",
    commit_confirm: "Bestätigen & in Wikibase schreiben",
    commit_missing_required: "Pflichtfelder sind noch leer: {fields}",
    commit_missing_required_block:
      "Speichern nicht möglich: Pflichtfelder fehlen: {fields}",
    commit_incomplete_ack:
      "Trotzdem speichern — der Eintrag bleibt unvollständig",

    stmt_loading: "Wird geladen…",
    stmt_empty: "Noch keine Einträge.",
    stmt_add_button: "{label} hinzufügen",
    stmt_edit_button: "Bearbeiten",
    stmt_remove_button: "Entfernen",
    stmt_undo_button: "Rückgängig",
    stmt_delete_confirm: "Sicher?",
    stmt_delete_yes: "Ja",
    stmt_delete_no: "Nein",
    stmt_pending: "ausstehend",
    stmt_snak_type: "Werttyp",
    stmt_snak_value: "Hat Wert",
    stmt_snak_unknown: "Unbekannter Wert",
    stmt_snak_no_value: "Kein Wert",
    stmt_display_unknown: "Unbekannter Wert",
    stmt_display_no_value: "Kein Wert",
    stmt_dialog_add: "{label} hinzufügen",
    stmt_dialog_edit: "{label} bearbeiten",
    stmt_save_button: "Speichern",
    stmt_cancel_button: "Abbrechen",
    stmt_sources_section: "Quellen",
    stmt_add_source: "Quelle hinzufügen",
    stmt_remove_source: "Entfernen",
    stmt_source_count: "{count} Quelle(n) hinterlegt",
    stmt_missing_required: "Pflichtfelder fehlen: {fields}",

    field_add_item: "Hinzufügen",

    datetime_use_picker: "Datumsauswahl verwenden",
    datetime_use_custom: "Eigenen Wert eingeben",
    datetime_format_hint:
      "Format: +JJJJ-MM-TTTHH:MM:SSZ — 00 für unbekannte Teile verwenden (z. B. +2020-00-00T00:00:00Z für Jahresgenauigkeit).",
    datetime_invalid_format:
      "Wert entspricht nicht dem erwarteten Wikibase-Zeitformat.",

    search_placeholder: "Nach Label suchen oder QID eingeben…",
    search_change: "Ändern",
    search_cancel: "Abbrechen",
    search_clear: "Löschen",
    search_failed: "Suche fehlgeschlagen",
    footer_impressum: "Impressum",
  },
};

export function useI18n() {
  function t(key, params = {}) {
    const msg = messages[locale.value]?.[key] ?? messages.en[key] ?? key;
    return msg.replace(/\{(\w+)\}/g, (_, k) => params[k] ?? `{${k}}`);
  }
  return { t, locale, setLocale };
}
