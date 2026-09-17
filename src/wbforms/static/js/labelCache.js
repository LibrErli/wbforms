import { apiFetch } from "./api.js";

const _cache = {};

export async function getLabel(qid, language = "de") {
  if (!qid) return "";
  const key = `${qid}:${language}`;
  if (key in _cache) {
    console.log(`getLabel - cache hit for ${qid}:`, _cache[key]);
    return _cache[key];
  }
  console.log(`getLabel - fetching label for ${qid}...`);
  _cache[key] = ""; // optimistic: prevent duplicate in-flight fetches
  try {
    const r = await apiFetch(
      `/api/entity-label?qid=${encodeURIComponent(qid)}&language=${encodeURIComponent(language)}`,
    );
    const label = r?.label && r.label !== qid ? r.label : "";
    _cache[key] = label;
    console.log(`getLabel - got label for ${qid}:`, label);
    return label;
  } catch (e) {
    console.log(`getLabel - error fetching label for ${qid}:`, e);
    return "";
  }
}
