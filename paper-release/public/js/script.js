// public/js/script.js
// Defensive, drop-in frontend script for Cetara datatable & datagraph pages.
// - tolerant of missing DOM elements
// - does not force client-side auth redirects
// - supports mw / mwco_da variants
// - conservative: does not change server behavior

// ------------------------- Header / display helpers -------------------------
const HEADER_KEY_OVERRIDES = {
  'membrane':               'Membrane',
  'type':                   'Type',
  'pfas':                   'PFAS',
  'removal_rate':           'Removal Rate (%)',
  'a_water_permeance':      'Water Permeance (LMH bar⁻¹)',
  'b_solute_permeance':     'B (LMH)',
  'a_b':                    'A/B: Water-Solute Selectivity (bar⁻¹)',
  'mwco_da':                'MWCO (Da)',
  'mwco':                   'MWCO (Da)',
  'water_contact_angle':    'Water Contact Angle (°)',
  'isoelectric_point':      'Isoelectric Point',
  'isoelectricpoint':       'Isoelectric Point',
  'initial_concentration':  'Initial Concentration (ng/L)',
  'initial_concentration_ng_l':'Initial Concentration (ng/L)',
  'pressure':               'Pressure (psi)',
  'is_mm':                  'IS (mM)',
  'ismm':                   'IS (mM)',
  'ph':                     'pH',
  'doi':                    'DOI',
};

const COLUMN_ORDER = [
  "membrane", "type", "pfas", "removal_rate",
  "a_water_permeance", "b_solute_permeance", "a_b",
  "mwco_da", "water_contact_angle", "isoelectric_point",
  "initial_concentration", "pressure", "is_mm", "ph", "doi"
];

const WORD_OVERRIDES = { 'pfas': 'PFAS', 'mw': 'Mw', 'ph': 'pH' };

function formatHeader(header) {
  if (!header) return header;
  const key = String(header).toLowerCase();
  if (HEADER_KEY_OVERRIDES[key]) return HEADER_KEY_OVERRIDES[key];
  return String(header).split('_').map(w => {
    const lw = w.toLowerCase();
    if (WORD_OVERRIDES[lw]) return WORD_OVERRIDES[lw];
    return w.charAt(0).toUpperCase() + w.slice(1).toLowerCase();
  }).join(' ');
}

function formatDecimal(value, columnName) {
  const decimalColumns = ['removal_rate', 'a_b', 'b_solute_permeance', 'a_water_permeance'];
  const integerColumns = ['initial_concentration'];
  if (value == null) return value;
  if (decimalColumns.includes(columnName)) {
    const num = parseFloat(value);
    if (!isNaN(num)) return num.toFixed(2);
  }
  if (integerColumns.includes(columnName)) {
    const num = parseFloat(value);
    if (!isNaN(num)) return num.toFixed(0);
  }
  return value;
}

// ------------------------- Spinner helpers -------------------------
const spinnerContainer = document.querySelector('.loading-spinner-container');
function showSpinner(){ if (spinnerContainer) spinnerContainer.style.display = 'flex'; }
function hideSpinner(){ if (spinnerContainer) spinnerContainer.style.display = 'none'; }

// ------------------------- App state -------------------------
let researchDataGlobal = [];
let compareList = [];
const compareButton = document.getElementById("compareButton");

// ------------------------- Auth-safe loadData -------------------------
async function loadData() {
  showSpinner();
  try {
    const token = localStorage.getItem("token");
    // Client will use /data (public router) when server exposes it.
    // If your server exposes a different public endpoint, change this.
    const endpoint = "/data"; // server should already expose public read at /data
    const headers = { "Content-Type": "application/json" };
    if (token) headers.Authorization = `Bearer ${token}`;

    console.debug("[loadData] fetching", endpoint, "with token?", !!token);
    const response = await fetch(endpoint, { method: "GET", headers });
    if (!response.ok) {
      // surface friendly message but keep page usable
      const body = await response.text().catch(()=>null);
      throw new Error(`Failed to fetch data (${response.status})${body ? ': ' + body : ''}`);
    }

    const data = await response.json();
    if (!Array.isArray(data)) {
      console.warn("[loadData] expected array, got:", data);
      throw new Error("Unexpected data shape from server");
    }

    // stable ordering if `id` exists
    if (data.length && data[0].id !== undefined) {
      data.sort((a,b) => (a.id||0) - (b.id||0));
    }

    researchDataGlobal = data;
    populateFilters(data);

    // If page has table render it
    if (document.getElementById("dataTable")) {
      renderTable(data);
      hookFilters();
    }

    // If page has a chart renderer function (separate file), call it
    if (typeof renderChartFromData === 'function') {
      try { renderChartFromData(data); } catch (e) { console.warn("renderChartFromData threw:", e); }
    }

    console.info("[loadData] loaded rows:", data.length);
  } catch (error) {
    console.error("Error loading data:", error);
    // show message inside chart area if present
    const chartErrorMsg = document.getElementById('chartErrorMsg');
    if (chartErrorMsg) {
      chartErrorMsg.style.display = 'block';
      chartErrorMsg.textContent = 'Error loading data: ' + (error.message || 'unknown');
    }
  } finally {
    hideSpinner();
  }
}

// ------------------------- Filters hooking & applying -------------------------
function hookFilters() {
  // safe attach: remove then add where possible
  const si = document.getElementById("searchInput");
  if (si) { try { si.removeEventListener("input", applyAllFilters); } catch(_){}; si.addEventListener("input", applyAllFilters); }

  const fm = document.getElementById("filterMembrane");
  if (fm) { try { fm.removeEventListener("change", applyAllFilters); } catch(_){}; fm.addEventListener("change", applyAllFilters); }

  const fp = document.getElementById("filterPFAS");
  if (fp) { try { fp.removeEventListener("change", applyAllFilters); } catch(_){}; fp.addEventListener("change", applyAllFilters); }

  const fr = document.getElementById("filterRemovalRate");
  if (fr) { try { fr.removeEventListener("input", applyAllFilters); } catch(_){}; fr.addEventListener("input", applyAllFilters); }

  const fmw = document.getElementById("filterMW") || document.getElementById("filterMWCO_DA");
  if (fmw) { try { fmw.removeEventListener("input", applyAllFilters); } catch(_){}; fmw.addEventListener("input", applyAllFilters); }
}

function applyAllFilters() {
  try {
    const searchValue = (document.getElementById("searchInput") || {}).value || "";
    const membrane    = (document.getElementById("filterMembrane") || {}).value || "";
    const pfas        = (document.getElementById("filterPFAS") || {}).value || "";

    const minRemovalRaw = (document.getElementById("filterRemovalRate") || {}).value;
    const minRemoval = minRemovalRaw === "" ? NaN : parseFloat(minRemovalRaw);

    const mwInputEl = document.getElementById("filterMW") || document.getElementById("filterMWCO_DA");
    const maxMWraw = mwInputEl ? mwInputEl.value : "";
    const maxMW = maxMWraw === "" ? NaN : parseFloat(maxMWraw);

    const filtered = (researchDataGlobal || []).filter(row => {
      if (!row) return false;

      const rowValues = Object.values(row).map(v => v == null ? '' : String(v).toLowerCase());
      const matchesSearch = !searchValue || rowValues.some(val => val.includes(String(searchValue).toLowerCase()));

      const matchesMembrane = !membrane || (row.membrane === membrane);
      const matchesPFAS = !pfas || (row.pfas === pfas);

      const rowRemoval = row.removal_rate == null ? NaN : parseFloat(row.removal_rate);
      const matchesRemoval = isNaN(minRemoval) || (!isNaN(rowRemoval) && rowRemoval >= minRemoval);

      // try several MW field names
      const mwField = (row.mw !== undefined) ? row.mw : (row.mwco_da !== undefined ? row.mwco_da : row.mwco);
      const rowMW = mwField == null ? NaN : parseFloat(mwField);
      const matchesMW = isNaN(maxMW) || (!isNaN(rowMW) && rowMW <= maxMW);

      return matchesSearch && matchesMembrane && matchesPFAS && matchesRemoval && matchesMW;
    });

    renderTable(filtered);
  } catch (err) {
    console.error("[applyAllFilters] error:", err);
  }
}

// ------------------------- Table rendering & compare logic -------------------------
function renderTable(dataArray) {
  const table = document.getElementById("dataTable");
  if (!table) return;
  const headerRow = document.getElementById("tableHeader");
  const tbody = table.querySelector("tbody");
  if (headerRow) headerRow.innerHTML = "";
  if (tbody) tbody.innerHTML = "";

  if (!Array.isArray(dataArray) || dataArray.length === 0) {
    if (tbody) {
      const tr = document.createElement("tr");
      const td = document.createElement("td");
      td.colSpan = Math.max(1, COLUMN_ORDER.length + 1);
      td.textContent = "No rows to display.";
      tr.appendChild(td);
      tbody.appendChild(tr);
    }
    return;
  }

  // Choose header columns: prefer COLUMN_ORDER if present in first row, else fallback
  const first = dataArray[0] || {};
  const availableKeys = new Set(Object.keys(first));
  const headerCols = [];
  COLUMN_ORDER.forEach(k => { if (availableKeys.has(k)) headerCols.push(k); });
  if (headerCols.length === 0) Object.keys(first).forEach(k => headerCols.push(k));

  // header - select column
  if (headerRow) {
    const thSelect = document.createElement("th");
    thSelect.textContent = "Select";
    headerRow.appendChild(thSelect);
  }

  headerCols.forEach(col => {
    const th = document.createElement("th");
    th.textContent = formatHeader(col);
    headerRow.appendChild(th);
  });

  dataArray.forEach(row => {
    const tr = document.createElement("tr");
    const tdSelect = document.createElement("td");
    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.className = "compare-checkbox";
    cb.value = row.membrane || JSON.stringify(row);
    tdSelect.appendChild(cb);
    tr.appendChild(tdSelect);

    headerCols.forEach(col => {
      const td = document.createElement("td");

      if (col === "doi" && row[col]) {
        const a = document.createElement("a");
        a.href = row[col];
        a.textContent = row[col];
        a.target = "_blank";
        td.className = "doi-cell";
        td.appendChild(a);
      } else {
        let val = row[col];
        if (val === undefined) {
          if (col === 'mw' && row.mwco_da !== undefined) val = row.mwco_da;
          if (col === 'mwco_da' && row.mw !== undefined) val = row.mw;
          if (col === 'initial_concentration' && row.initial_concentration_ng_l !== undefined) val = row.initial_concentration_ng_l;
        }
        td.textContent = (formatDecimal(val, col) ?? (val !== undefined ? String(val) : "N/A"));
      }

      tr.appendChild(td);
    });

    tbody.appendChild(tr);
  });

  // attach compare handlers
  try {
    const checkboxes = document.querySelectorAll(".compare-checkbox");
    checkboxes.forEach(box => {
      try { box.removeEventListener("change", compareCheckboxHandler); } catch(_) {}
      box.addEventListener("change", compareCheckboxHandler);
    });
  } catch (e) {
    console.warn("compare-checkbox attach failed:", e);
  }

  // update compare button
  try {
    compareList = Array.from(document.querySelectorAll(".compare-checkbox")).filter(b => b.checked).map(b => b.value);
    if (compareButton) {
      compareButton.disabled = compareList.length < 2;
      compareButton.textContent = compareList.length > 0 ? `Compare Selected (${compareList.length})` : "Compare Selected";
    }
  } catch (e) { /* ignore */ }
}

function compareCheckboxHandler() {
  try {
    const checkboxes = document.querySelectorAll(".compare-checkbox");
    compareList = Array.from(checkboxes).filter(b => b.checked).map(b => b.value);
    if (compareButton) {
      compareButton.disabled = compareList.length < 2;
      compareButton.textContent = compareList.length > 0 ? `Compare Selected (${compareList.length})` : "Compare Selected";
    }
  } catch (err) {
    console.warn("compareCheckboxHandler error:", err);
  }
}

// compare button action (if present)
if (compareButton) {
  compareButton.addEventListener("click", () => {
    if (compareList.length < 2) {
      alert("Select at least two membranes to compare.");
      return;
    }
    const params = new URLSearchParams();
    params.set("compare", compareList.join(","));
    // datagraph.html expects ?compare=...
    window.location.href = "datagraph.html?" + params.toString();
  });
}

// ------------------------- Login / registration / logout -------------------------
const loginForm = document.getElementById("loginForm");
if (loginForm) {
  loginForm.addEventListener("submit", async function (e) {
    e.preventDefault();
    const username = document.getElementById("username").value;
    const password = document.getElementById("password").value;
    try {
      const response = await fetch("/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "Login failed");
      localStorage.setItem("token", data.token);
      if (typeof updateNavbarLinks === 'function') updateNavbarLinks();
      await loadData();
    } catch (error) {
      console.error("Login failed:", error);
      alert("Login failed: " + (error.message || "unknown"));
    }
  });
}

const registerForm = document.getElementById("registerForm");
if (registerForm) {
  registerForm.addEventListener("submit", async function (e) {
    e.preventDefault();
    const payload = {
      firstName:   document.getElementById("firstName").value,
      lastName:    document.getElementById("lastName").value,
      username:    document.getElementById("username").value,
      email:       document.getElementById("email").value,
      phone:       document.getElementById("phone").value,
      institution: document.getElementById("institution").value,
      password:    document.getElementById("password").value,
    };
    try {
      const response = await fetch("/register", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || "Registration failed");
      alert("Registration successful! You may now log in.");
      window.location.href = "index.html";
    } catch (error) {
      console.error("Registration failed:", error);
      alert("Registration failed: " + (error.message || "unknown"));
    }
  });
}

function logout() {
  localStorage.removeItem("token");
  localStorage.removeItem('chatHistory');
  if (typeof updateNavbarLinks === 'function') updateNavbarLinks();
  // try to reload public data after logout
  loadData();
}

// ------------------------- Navbar updater (non-destructive) -------------------------
function updateNavbarLinks() {
  const token = localStorage.getItem("token");
  const isLoggedIn = !!token;

  const navResearch = document.getElementById("navResearch");
  const navLogout   = document.getElementById("navLogout");
  const navAccount  = document.getElementById("navAccountLoggedOut");
  const navTable    = document.getElementById("navTable");
  const navSubmit   = document.getElementById("navSubmit");

  if (navResearch) navResearch.style.display = isLoggedIn ? "block" : "none";
  if (navLogout)   navLogout.style.display   = isLoggedIn ? "block" : "none";
  if (navAccount)  navAccount.style.display  = isLoggedIn ? "none"  : "block";
  if (navTable)    navTable.style.display    = isLoggedIn ? "block" : "block"; // allow public table view
  if (navSubmit)   navSubmit.style.display   = isLoggedIn ? "block" : "none";

  const loginSection = document.getElementById("loginSection");
  const dataSection  = document.getElementById("dataSection");
  const hero         = document.getElementById("heroSection");

  if (loginSection && dataSection) {
    loginSection.style.display = isLoggedIn ? "none"  : "block";
    dataSection.style.display  = "block";
    if (hero) hero.style.display = isLoggedIn ? "none" : "block";
  }

  // attempt to load data if on pages requiring it
  const isDataTablePage = !!document.getElementById('dataTable');
  const isDataGraphPage = !!document.getElementById('pfasChart');
  if (isDataTablePage || isDataGraphPage) {
    loadData();
  }
}

// ------------------------- Populate dropdowns -------------------------
function populateDropdown(id, dataSet) {
  const select = document.getElementById(id);
  if (!select) return;
  select.innerHTML = '<option value="">All</option>';
  const arr = (dataSet instanceof Set) ? Array.from(dataSet) : Array.from(dataSet || []);
  arr.sort((a,b) => {
    try { return String(a).localeCompare(String(b)); } catch { return 0; }
  });
  arr.forEach(value => {
    if (value === null || value === undefined) return;
    const opt = document.createElement("option");
    opt.value = value;
    opt.textContent = value;
    select.appendChild(opt);
  });
}

function populateFilters(data) {
  const membraneSet = new Set();
  const pfasSet     = new Set();
  (data || []).forEach(row => {
    if (!row) return;
    if (row.membrane) membraneSet.add(row.membrane);
    if (row.pfas)     pfasSet.add(row.pfas);
  });
  populateDropdown("filterMembrane", membraneSet);
  populateDropdown("filterPFAS", pfasSet);
}

// ------------------------- Init -------------------------
document.addEventListener("DOMContentLoaded", () => {
  try { updateNavbarLinks(); } catch (e) { console.warn("updateNavbarLinks error", e); }

  const dataSection = document.getElementById("dataSection");
  if (dataSection) {
    dataSection.style.display = "block";
    loadData();
  }

  // compact toggle UI (optional)
  const compactToggle = document.getElementById('compactToggle');
  if (compactToggle) {
    compactToggle.addEventListener('click', function() {
      var table = document.getElementById('dataTable');
      if (!table) return;
      var isCompact = table.classList.contains('compact');
      if (isCompact) {
        table.classList.remove('compact');
        this.innerHTML = '<i class="bi bi-arrows-angle-contract me-1"></i>Compact View';
        this.classList.remove('active');
      } else {
        table.classList.add('compact');
        this.innerHTML = '<i class="bi bi-arrows-angle-expand me-1"></i>Normal View';
        this.classList.add('active');
      }
    });
  }
});

// ------------------------- Dev-friendly: do not block dev tools -------------------------
document.addEventListener("keydown", e => {
  // no-op: developers may inspect freely
});
document.addEventListener("copy", e => {
  // no-op: do not block copying
});
