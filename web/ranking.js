// Shared "percentile-rank + slider-weighted score" engine used by both
// opportunity.html (housing) and opportunity_tracts.html (tracts). Each
// page defines its own METRICS array, computeRawMetrics(), renderList(),
// and rerank() — only this generic layer is identical between them.
//
// Percentile rank is only meaningful relative to the whole eligible set,
// so it can't be a pure per-row function; it's built once per metric at
// load time (assignPercentiles), and every slider move afterward just
// reruns computeScore()+sort — no server round-trip, no recomputation of
// raw values or percentiles.

function haversineMiles(lat1, lon1, lat2, lon2) {
  const R = 3958.8;
  const toRad = (d) => (d * Math.PI) / 180;
  const dLat = toRad(lat2 - lat1);
  const dLon = toRad(lon2 - lon1);
  const a = Math.sin(dLat / 2) ** 2 + Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLon / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(a));
}

// Brute-force nearest-store search — a few thousand rows x ~1,300
// grocery/mass stores is a few million haversine calls, well under a
// second in JS. Runs once at load, not per slider move, so a spatial
// index (like the main map's heatmap uses) isn't needed here.
function nearestStoreMiles(lat, lon, stores) {
  let best = Infinity;
  for (const s of stores) {
    const d = haversineMiles(lat, lon, s.lat, s.lon);
    if (d < best) best = d;
  }
  return best;
}

// A row missing a given raw value gets a neutral 0.5 percentile for that
// metric — consistent with how the main map's "Min. units" filter treats
// unknown unit counts: unknown isn't penalized or rewarded, just neutral.
function assignPercentiles(features, rawKey, pctKey, higherIsBetter) {
  const withValue = features.filter((f) => f.properties[rawKey] != null && isFinite(f.properties[rawKey]));
  withValue.sort((a, b) => a.properties[rawKey] - b.properties[rawKey]);
  const n = withValue.length;
  withValue.forEach((f, i) => {
    const rank = n <= 1 ? 0.5 : i / (n - 1);
    f.properties[pctKey] = higherIsBetter ? rank : 1 - rank;
  });
  for (const f of features) {
    if (f.properties[rawKey] == null || !isFinite(f.properties[rawKey])) {
      f.properties[pctKey] = 0.5;
    }
  }
}

// Requires the page's own global METRICS array (one { key, ... } per
// scored factor) to be defined by the time this is called.
function computeScore(feature, weights) {
  return METRICS.reduce((sum, m) => sum + weights[m.key] * feature.properties[`_pct_${m.key}`], 0);
}

function readWeights() {
  const weights = {};
  for (const m of METRICS) {
    weights[m.key] = Number(document.getElementById(`slider-${m.key}`).value);
  }
  return weights;
}

function buildSliders(onChange) {
  const container = document.getElementById("slider-list");
  container.innerHTML = METRICS.map(
    (m) => `
      <div class="slider-row">
        <label>${m.label}<span class="weight-value" id="weight-${m.key}">${m.default}</span></label>
        <input type="range" id="slider-${m.key}" min="0" max="10" step="1" value="${m.default}">
      </div>
    `
  ).join("");

  for (const m of METRICS) {
    const slider = document.getElementById(`slider-${m.key}`);
    slider.addEventListener("input", () => {
      document.getElementById(`weight-${m.key}`).textContent = slider.value;
      onChange();
    });
  }
}

async function loadGeoJSON(url) {
  const res = await fetch(url);
  return res.json();
}

// Event delegation on the tbody, not a per-row listener — rows are
// replaced wholesale on every rerank(), so a listener attached directly
// to a <tr> would be gone after the very next slider move.
document.getElementById("list-body").addEventListener("click", (e) => {
  const row = e.target.closest("tr[data-href]");
  if (row) window.location.href = row.dataset.href;
});
