// public/js/admin.js

// ---------------------- AUTH HEADER ----------------------
function authHeader() {
  const token = localStorage.getItem('token');
  return token ? { 'Authorization': `Bearer ${token}` } : {};
}

// ---------------------- MODAL TOGGLE ----------------------
function setupModal() {
  const openBtn   = document.getElementById('add-data-btn');
  const modal     = document.getElementById('add-data-modal');
  const cancelBtn = document.getElementById('cancel-btn');

  openBtn.addEventListener('click', () => modal.classList.remove('hidden'));
  cancelBtn.addEventListener('click', () => modal.classList.add('hidden'));

  // Enable custom‑ID input only when that radio is checked
  const radios   = document.querySelectorAll('input[name="id-option"]');
  const customIn = document.getElementById('custom-id');
  radios.forEach(r => {
    r.addEventListener('change', () => {
      customIn.disabled = (document.querySelector('input[name="id-option"]:checked').value !== 'custom');
    });
  });
}

// ---------------------- LOAD & RENDER MAIN DATA ----------------------
async function loadData() {
  const res = await fetch('/data', { headers: authHeader() });
  if (!res.ok) {
    console.error('Failed to fetch data:', res.status);
    return;
  }
  const items = await res.json();
  items.sort((a, b) => a.id - b.id);
  renderAdminTable(items);
}

function renderAdminTable(items) {
  const tbody = document.querySelector('#data-table tbody');
  tbody.innerHTML = '';
  items.forEach(item => {
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td><input type="checkbox" class="row-checkbox" data-id="${item.id}"></td>
      <td>${item.id}</td>
      <td>${item.membrane}</td>
      <td>${item.mwco_da}</td>
      <td>${item.pfas}</td>
      <td>${item.removal_rate}</td>
      <td>${item.isoelectric_point ?? ''}</td>
      <td>${item.water_contact_angle ?? ''}</td>
      <td>${item.mw ?? ''}</td>
      <td>${item.smiles ?? ''}</td>
      <td>${item.compound_size ?? ''}</td>
      <td>${item.log_kow ?? ''}</td>
      <td>${item.pka ?? ''}</td>
      <td>${item.initial_concentration ?? ''}</td>
      <td>${item.is_mm ?? ''}</td>
      <td>${item.pressure ?? ''}</td>
      <td>${item.ph ?? ''}</td>
      <td>${item.doi ?? ''}</td>
    `;
    tbody.appendChild(tr);
  });
  bindRowCheckboxes();
  updateDeleteButton();
}

// ---------------------- CHECKBOX & DELETE MAIN DATA ----------------------
function bindRowCheckboxes() {
  const boxes = document.querySelectorAll('.row-checkbox');
  boxes.forEach(b => b.addEventListener('change', updateDeleteButton));

  const selectAll = document.getElementById('select-all');
  if (selectAll) {
    selectAll.checked = false;
    selectAll.addEventListener('change', () => {
      boxes.forEach(b => b.checked = selectAll.checked);
      updateDeleteButton();
    });
  }
}

function updateDeleteButton() {
  const any = [...document.querySelectorAll('.row-checkbox')].some(b => b.checked);
  document.getElementById('delete-selected-btn')
          .classList.toggle('hidden', !any);
}

async function deleteSelected() {
  if (!confirm('Delete selected entries?')) return;
  const ids = [...document.querySelectorAll('.row-checkbox')]
                .filter(b => b.checked)
                .map(b => b.dataset.id);
  await Promise.all(ids.map(id =>
    fetch(`/data/${id}`, { method: 'DELETE', headers: authHeader() })
  ));
  loadData();
}

// ---------------------- ADD‑DATA FORM ----------------------
function getNextId(ids) {
  return ids.length ? ids[ids.length - 1] + 1 : 1;
}
function getLowestGap(ids) {
  for (let i = 1; i <= (ids[ids.length - 1] || 1); i++) {
    if (!ids.includes(i)) return i;
  }
  return getNextId(ids);
}

async function handleAddForm(e) {
  e.preventDefault();
  // Determine which ID to use
  const rows = [...document.querySelectorAll('#data-table tbody tr')];
  const ids  = rows.map(r => parseInt(r.children[1].textContent,10)).sort((a,b)=>a-b);
  const mode = document.querySelector('input[name="id-option"]:checked').value;
  let idValue;
  if (mode === 'next') idValue = getNextId(ids);
  else if (mode === 'lowest') idValue = getLowestGap(ids);
  else {
    idValue = parseInt(document.getElementById('custom-id').value, 10);
    if (!Number.isInteger(idValue) || idValue <= 0) {
      alert('Please enter a valid custom ID');
      return;
    }
  }

  // Gather form fields
  const fields = [
    'membrane','mwco_da','pfas','removal_rate','isoelectric_point',
    'water_contact_angle','mw','smiles','compound_size','log_kow',
    'pka','initial_concentration','is_mm','pressure','ph','doi'
  ];
  const payload = { id: idValue };
  fields.forEach(f => {
    const v = document.getElementById(f).value;
    payload[f] = (v === '') ? null : (isNaN(v) ? v : +v);
  });

  // Send to server
  const res = await fetch('/data', {
    method: 'POST',
    headers: {
      ...authHeader(),
      'Content-Type': 'application/json'
    },
    body: JSON.stringify(payload)
  });
  if (!res.ok) {
    const err = await res.text();
    alert('Failed to save entry: ' + err);
  }

  document.getElementById('add-data-form').reset();
  document.getElementById('add-data-modal').classList.add('hidden');
  loadData();
}

// ---------------------- CELL VIEWER MODAL ----------------------
function setupCellViewer() {
  const modal    = document.getElementById('view-modal');
  const textElem = document.getElementById('view-modal-text');
  const closeBtn = document.getElementById('view-modal-close');

  if (!modal || !textElem || !closeBtn) {
    console.warn('View modal elements missing; skipping setup.');
    return;
  }

  document.querySelector('#data-table tbody').addEventListener('click', e => {
    const td = e.target.closest('td');
    if (!td || td.querySelector('input[type="checkbox"]')) return;
    const txt = td.innerText.trim();
    if (!txt) return;
    textElem.textContent = txt;
    modal.classList.remove('hidden');
  });

  closeBtn.addEventListener('click', () => modal.classList.add('hidden'));
  modal.addEventListener('click', e => {
    if (e.target === modal) modal.classList.add('hidden');
  });
}

// ---------------------- SUBMISSIONS REVIEW ----------------------
async function loadSubmissions() {
  const res = await fetch('/user-data/pending', { headers: authHeader() });
  if (!res.ok) { console.error('Fetch subs failed:', res.status); return; }
  const subs = await res.json();
  renderSubmissionsTable(subs);
}

function renderSubmissionsTable(subs) {
  const tbody = document.querySelector('#submissions-table tbody');
  tbody.innerHTML = '';
  subs.forEach(s => {
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td><input type="checkbox" class="sub-checkbox" data-id="${s.id}"></td>
      <td>${s.id}</td>
      <td>${s.user_id}</td>
      <td>${s.membrane}</td>
      <td>${s.mwco_da}</td>
      <td>${s.pfas}</td>
      <td>${s.removal_rate}</td>
      <td>${s.isoelectric_point ?? ''}</td>
      <td>${s.water_contact_angle ?? ''}</td>
      <td>${s.mw ?? ''}</td>
      <td>${s.smiles ?? ''}</td>
      <td>${s.compound_size ?? ''}</td>
      <td>${s.log_kow ?? ''}</td>
      <td>${s.pka ?? ''}</td>
      <td>${s.initial_concentration ?? ''}</td>
      <td>${s.is_mm ?? ''}</td>
      <td>${s.pressure ?? ''}</td>
      <td>${s.ph ?? ''}</td>
      <td>${s.doi_reference ?? ''}</td>
      <td>${
        s.created_at
          ? new Date(s.created_at).toLocaleString()
          : ''
      }</td>
    `;
    tbody.appendChild(tr);
  });
  bindSubCheckboxes();
}

function bindSubCheckboxes() {
  const boxes = document.querySelectorAll('.sub-checkbox');
  boxes.forEach(b => b.addEventListener('change', updateSubButtons));

  const selectAll = document.getElementById('sub-select-all');
  if (selectAll) {
    selectAll.checked = false;
    selectAll.addEventListener('change', () => {
      boxes.forEach(b => b.checked = selectAll.checked);
      updateSubButtons();
    });
  }
}

function updateSubButtons() {
  const any = [...document.querySelectorAll('.sub-checkbox')].some(b => b.checked);
  document.getElementById('approve-selected-btn')
          .classList.toggle('hidden', !any);
  document.getElementById('reject-selected-btn')
          .classList.toggle('hidden', !any);
}

async function approveSelected() {
  const checked = [...document.querySelectorAll('.sub-checkbox')]
                    .filter(b => b.checked);
  for (const box of checked) {
    const subId = box.dataset.id;
    const choice = prompt(
      `Submission ${subId} ID assignment:\n` +
      `Type "next" for next ID, "lowest" for lowest gap, or enter a custom positive integer.`
    );
    if (choice === null) continue;
    await fetch(
      `/user-data/${subId}/approve?targetId=${encodeURIComponent(choice)}`,
      { method: 'POST', headers: authHeader() }
    );
  }
  loadSubmissions();
  loadData();
}

async function rejectSelected() {
  const ids = [...document.querySelectorAll('.sub-checkbox')]
                .filter(b => b.checked)
                .map(b => b.dataset.id);
  await Promise.all(ids.map(id =>
    fetch(`/user-data/${id}`, {
      method: 'DELETE',
      headers: authHeader()
    })
  ));
  loadSubmissions();
}

// ---------------------- INIT ----------------------
document.addEventListener('DOMContentLoaded', () => {
  setupModal();
  setupCellViewer();
  document.getElementById('add-data-form')
          .addEventListener('submit', handleAddForm);
  document.getElementById('delete-selected-btn')
          .addEventListener('click', deleteSelected);
  document.getElementById('approve-selected-btn')
          .addEventListener('click', approveSelected);
  document.getElementById('reject-selected-btn')
          .addEventListener('click', rejectSelected);
  loadData();
  loadSubmissions();
});
