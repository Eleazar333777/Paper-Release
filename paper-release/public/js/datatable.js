// datatable.js

// ─── Global state & globals ───────────────────────────────────────────
let researchDataGlobal = [];
let compareList = [];
const compareButton = document.getElementById('compareButton');

// ─── On load: protect page, show section, fetch data, bind filters ────
document.addEventListener('DOMContentLoaded', () => {
  // redirect if not logged in
//  if (!localStorage.getItem('token')) return window.location.href = '/';

  // show the data section
  document.getElementById('dataSection').style.display = 'block';

  // fetch & render data
  loadData();

  // wire up filter inputs
  ['searchInput','filterMembrane','filterPFAS','filterRemovalRate','filterMW']
    .forEach(id =>
      document.getElementById(id)
             .addEventListener('input', applyAllFilters)
    );
});

// ─── Fetch & initialize ───────────────────────────────────────────────
async function loadData() {
  showSpinner();
  try {
    const res = await fetch('/data', {
  //    headers: { Authorization: `Bearer ${localStorage.getItem('token')}` }
    });
    if (!res.ok) throw new Error('Failed to fetch data');
    const data = await res.json();
    data.sort((a, b) => a.membrane.localeCompare(b.membrane));
    researchDataGlobal = data;
    populateFilters(data);
    renderTable(data);
  } catch (err) {
    console.error('Error loading data:', err);
  } finally {
    hideSpinner();
  }
}

// ─── Filters ───────────────────────────────────────────────────────────
function applyAllFilters() {
  const sv   = document.getElementById('searchInput').value.toLowerCase();
  const mem  = document.getElementById('filterMembrane').value;
  const pfas = document.getElementById('filterPFAS').value;
  const minR = parseFloat(document.getElementById('filterRemovalRate').value);
  const maxM = parseFloat(document.getElementById('filterMW').value);

  const filtered = researchDataGlobal.filter(r => {
    const textMatch = Object.values(r).some(v =>
      String(v).toLowerCase().includes(sv)
    );
    const mMatch = !mem  || r.membrane === mem;
    const pMatch = !pfas || r.pfas === pfas;
    const rMatch = isNaN(minR) || parseFloat(r.removal_rate) >= minR;
    const mWMatch= isNaN(maxM) || parseFloat(r.mw)           <= maxM;
    return textMatch && mMatch && pMatch && rMatch && mWMatch;
  });

  renderTable(filtered);
}

// ─── Dropdown population ───────────────────────────────────────────────
function populateDropdown(id, set) {
  const sel = document.getElementById(id);
  sel.innerHTML = '<option value="">All</option>';
  Array.from(set).sort().forEach(val => {
    const opt = document.createElement('option');
    opt.value = opt.textContent = val;
    sel.appendChild(opt);
  });
}

function populateFilters(data) {
  const membranes = new Set();
  const pfasst    = new Set();
  data.forEach(r => {
    if (r.membrane) membranes.add(r.membrane);
    if (r.pfas)     pfasst.add(r.pfas);
  });
  populateDropdown('filterMembrane', membranes);
  populateDropdown('filterPFAS',     pfasst);
}

// ─── Table rendering & compare logic ─────────────────────────────────
function renderTable(dataArray) {
  const table  = document.getElementById('dataTable');
  const theadR = table.querySelector('thead tr');
  const tbody  = table.querySelector('tbody');

  // clear out
  theadR.innerHTML = '';
  tbody.innerHTML  = '';

  // header row
  const selTh = document.createElement('th');
  selTh.textContent = 'Select';
  theadR.appendChild(selTh);

  if (dataArray.length) {
    Object.keys(dataArray[0])
      .filter(c => c !== 'id')
      .forEach(c => {
        const th = document.createElement('th');
        th.textContent = formatHeader(c);
        theadR.appendChild(th);
      });
  }

  // data rows
  dataArray.forEach(r => {
    const tr = document.createElement('tr');
    // checkbox cell
    const td0 = document.createElement('td');
    const cb  = document.createElement('input');
    cb.type  = 'checkbox';
    cb.className = 'compare-checkbox';
    cb.value = r.membrane;
    td0.appendChild(cb);
    tr.appendChild(td0);

    // other cells
    Object.entries(r)
      .filter(([c]) => c !== 'id')
      .forEach(([c, v]) => {
        const td = document.createElement('td');
        if (c === 'doi' && v) {
          const a = document.createElement('a');
          a.href        = v;
          a.textContent = v;
          a.target      = '_blank';
          td.className  = 'doi-cell';
          td.appendChild(a);
        } else {
          td.textContent = v ?? 'N/A';
        }
        tr.appendChild(td);
      });

    tbody.appendChild(tr);
  });

  // compare-button logic
  const boxes = table.querySelectorAll('.compare-checkbox');
  boxes.forEach(box =>
    box.addEventListener('change', () => {
      compareList = Array.from(boxes)
        .filter(b => b.checked)
        .map(b => b.value);
      compareButton.disabled = compareList.length < 2;
      compareButton.textContent = compareList.length
        ? `Compare Selected (${compareList.length})`
        : 'Compare Selected';
    })
  );
}

// ─── Compare click handler ────────────────────────────────────────────
compareButton.addEventListener('click', () => {
  if (compareList.length < 2) {
    alert('Select at least two membranes to compare.');
    return;
  }
  const params = new URLSearchParams({ compare: compareList.join(',') });
  window.location.href = 'datagraph.html?' + params;
});
