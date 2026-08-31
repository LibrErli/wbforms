import { apiFetch } from "./api.js";

const _cache = {};

export async function getLabel(qid, language = "de") {
  if (!qid) return "";
  const key = `${qid}:${language}`;
  if (key in _cache) return _cache[key];
  _cache[key] = ""; // optimistic: prevent duplicate in-flight fetches
  try {
    const r = await apiFetch(
      `/api/entity-label?qid=${encodeURIComponent(qid)}&language=${encodeURIComponent(language)}`,
    );
    const label = r?.label && r.label !== qid ? r.label : "";
    _cache[key] = label;
    return label;
  } catch {
    return "";
  }
}
