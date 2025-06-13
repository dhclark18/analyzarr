export async function fetchSeries() {
  const base = window._env_.SONARR_URL;
  const key  = window._env_.SONARR_API_KEY;
  const res  = await fetch(`${base}/api/v3/series`, {
    headers: { 'X-Api-Key': key }
  });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}
