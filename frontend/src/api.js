// src/api.js

/**
 * Fetch all series from Sonarr, including their seasons array.
 */
export async function fetchSeries() {
  const base = window._env_.SONARR_URL;
  const key  = window._env_.SONARR_API_KEY;
  const res  = await fetch(
    `${base}/api/v3/series?embed=seasons`,   // ← embed seasons here
    { headers: { 'X-Api-Key': key } }
  );
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();                        // [ { id, title, seasons: […], … }, … ]
}

/**
 * Fetch counts of problematic episodes grouped by series.
 */
export async function fetchMismatchCounts() {
  const res = await fetch('/api/mismatches');
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();  // [ { seriesTitle, count }, … ]
}
