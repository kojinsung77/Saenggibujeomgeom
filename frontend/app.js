/* =============================================================
   생활기록부 점검 — 프론트엔드 단일 페이지 앱
   ============================================================= */
'use strict';

/* -------------------- API 엔드포인트 -------------------- */
const API = {
  UPLOAD: '/api/upload',
  DB_BUILD: '/api/db/build',
  DB_STATUS: '/api/db/status',
  STUDENTS: '/api/students',
  STUDENT_DETAILS: (id) => `/api/students/${id}/details`,
  SEARCH: '/api/search',
  GEMINI_CONNECT: '/api/gemini/connect',
  PROMPT: '/api/prompt',
  PROMPT_RESET: '/api/prompt/reset',
  INSPECT_START: '/api/inspect/start',
  INSPECT_STREAM: (id) => `/api/inspect/stream/${id}`,
  INSPECT_CANCEL: (id) => `/api/inspect/cancel/${id}`,
  INSPECTIONS: '/api/inspections',
  RESULTS: '/api/results',
  RESULTS_EXPORT: '/api/results/export',
};

/* -------------------- 영역 정의 -------------------- */
const AREA_DEFS = [
  { key: 'subject_grades',       order: '①', title: '교과학습발달상황', short: '교과성적', required: true },
  { key: 'subject_details',      order: '②', title: '세부능력및특기사항', short: '세특', required: false },
  { key: 'creative_activities',  order: '③', title: '창의적체험활동',    short: '창체', required: false },
  { key: 'volunteer_activities', order: '④', title: '봉사활동상황',      short: '봉사', required: false },
  { key: 'behavior_opinion',     order: '⑤', title: '행동특성및종합의견', short: '행특', required: false },
  { key: 'grade_history',        order: '⑥', title: '학년반이력',        short: '학년반이력', required: false },
];
const AREA_BY_KEY = Object.fromEntries(AREA_DEFS.map(a => [a.key, a]));
const INSPECTABLE_AREAS = ['subject_details', 'creative_activities', 'volunteer_activities', 'behavior_opinion'];

const MAX_UPLOAD_BYTES = 50 * 1024 * 1024;
const ALLOWED_EXTS = ['.xls', '.xlsx'];

/* -------------------- 전역 상태 -------------------- */
const state = {
  uploadedFiles: {},   // { area: { file_id, filename, size } }
  dbStatus: null,      // { exists, students, records }
  apiKey: null,        // 메모리 전용
  availableModels: [],
  currentInspectionId: null,
  eventSource: null,
  inspectionResults: [],
  inspectionHistory: [],
  selectedInspectionId: null,
  resultFilter: 'all', // 'all' | 'violations' | 'normals'
  students: [],
  currentStudentDetail: null,
  classesByGrade: {},  // { grade: [class_no...] }
  liveViolations: 0,
};

/* -------------------- 유틸리티 -------------------- */
function $(sel, root = document) { return root.querySelector(sel); }
function $$(sel, root = document) { return Array.from(root.querySelectorAll(sel)); }

function escapeHtml(str) {
  if (str === null || str === undefined) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function formatBytes(n) {
  if (!n && n !== 0) return '';
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

function formatDateTime(iso) {
  if (!iso) return '-';
  try {
    const d = new Date(iso);
    if (isNaN(d.getTime())) return iso;
    const pad = (n) => String(n).padStart(2, '0');
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
  } catch { return iso; }
}

function truncate(s, n = 80) {
  if (!s) return '';
  const t = String(s).replace(/\s+/g, ' ').trim();
  return t.length > n ? t.slice(0, n) + '…' : t;
}

function formatDuration(seconds) {
  if (seconds === null || seconds === undefined || isNaN(seconds)) return '-';
  const s = Math.max(0, Math.round(seconds));
  if (s < 60) return `${s}초`;
  const m = Math.floor(s / 60);
  const rem = s % 60;
  if (m < 60) return rem > 0 ? `${m}분 ${rem}초` : `${m}분`;
  const h = Math.floor(m / 60);
  const mm = m % 60;
  return mm > 0 ? `${h}시간 ${mm}분` : `${h}시간`;
}

/* -------------------- 토스트 -------------------- */
function showToast(message, kind = 'info', duration = 3800) {
  const container = $('#toast-container');
  if (!container) return;
  const el = document.createElement('div');
  el.className = `toast toast-${kind}`;
  el.textContent = message;
  container.appendChild(el);
  setTimeout(() => {
    el.classList.add('toast-out');
    setTimeout(() => el.remove(), 220);
  }, duration);
}

/* -------------------- 공통 fetch 래퍼 -------------------- */
async function api(method, url, body, opts = {}) {
  const init = { method, headers: {} };
  if (body !== undefined) {
    if (body instanceof FormData) {
      init.body = body; // Content-Type 자동
    } else {
      init.headers['Content-Type'] = 'application/json';
      init.body = JSON.stringify(body);
    }
  }
  const res = await fetch(url, init);
  if (!res.ok) {
    let msg = `${method} ${url} 실패 (HTTP ${res.status})`;
    try {
      const err = await res.json();
      if (err && (err.detail || err.message)) {
        msg = err.detail || err.message;
      }
    } catch { /* 본문 없을 수도 */ }
    const e = new Error(msg);
    e.status = res.status;
    throw e;
  }
  if (opts.raw) return res;
  const ct = res.headers.get('content-type') || '';
  if (ct.includes('application/json')) return res.json();
  return res.text();
}

/* -------------------- 탭 라우팅 -------------------- */
const TABS = ['upload', 'search', 'inspect', 'validate', 'results', 'guide'];

function activateTab(name) {
  if (!TABS.includes(name)) name = 'upload';
  TABS.forEach((t) => {
    const panel = document.getElementById(`tab-${t}`);
    const link = document.querySelector(`.tab-link[data-tab="${t}"]`);
    if (!panel || !link) return;
    const active = t === name;
    panel.hidden = !active;
    link.classList.toggle('active', active);
  });

  // 탭 진입 시 데이터 로드
  if (name === 'search') {
    if (!state.students.length) loadStudents();
  } else if (name === 'inspect') {
    refreshPromptIfNeeded();
  } else if (name === 'validate') {
    initValidateTab();
  } else if (name === 'results') {
    loadInspections();
  }
}

function setupTabRouting() {
  const handler = () => {
    const hash = (location.hash || '#upload').replace(/^#/, '');
    activateTab(hash);
  };
  window.addEventListener('hashchange', handler);
  handler();
}

/* -------------------- 모달 -------------------- */
function openModal(title, bodyNodeOrHTML) {
  const overlay = $('#modal-overlay');
  const body = $('#modal-body');
  $('#modal-title').textContent = title || '상세';
  body.innerHTML = '';
  if (typeof bodyNodeOrHTML === 'string') {
    body.innerHTML = bodyNodeOrHTML;
  } else if (bodyNodeOrHTML instanceof Node) {
    body.appendChild(bodyNodeOrHTML);
  }
  overlay.hidden = false;
}

function closeModal() {
  $('#modal-overlay').hidden = true;
  $('#modal-body').innerHTML = '';
}

/* -------------------- DB 상태 뱃지 -------------------- */
function updateDbBadge() {
  const badge = $('#db-status-badge');
  if (!badge) return;
  const text = badge.querySelector('.status-text');
  badge.classList.remove('status-pill-ok', 'status-pill-warn', 'status-pill-muted');
  if (state.dbStatus && state.dbStatus.exists) {
    const stud = state.dbStatus.students || 0;
    badge.classList.add('status-pill-ok');
    text.textContent = `DB 구축됨 (${stud}명)`;
  } else {
    badge.classList.add('status-pill-muted');
    text.textContent = 'DB 미구축';
  }
}

function updateGeminiBadge(status) {
  const badge = $('#gemini-status-badge');
  if (!badge) return;
  const text = badge.querySelector('.status-text');
  badge.classList.remove('status-pill-ok', 'status-pill-warn', 'status-pill-muted');
  if (status === 'connected') {
    badge.classList.add('status-pill-ok');
    text.textContent = 'Gemini 연결됨';
  } else if (status === 'connecting') {
    badge.classList.add('status-pill-warn');
    text.textContent = '연결 중…';
  } else {
    badge.classList.add('status-pill-muted');
    text.textContent = 'Gemini 미연결';
  }
}

async function refreshDbStatus() {
  try {
    const s = await api('GET', API.DB_STATUS);
    state.dbStatus = s;
  } catch (e) {
    state.dbStatus = { exists: false };
  }
  updateDbBadge();
  updateDbBuildButton();
}

/* =============================================================
   탭 1: 업로드
   ============================================================= */
function renderUploadCards() {
  const grid = $('#upload-grid');
  grid.innerHTML = '';
  AREA_DEFS.forEach((def) => {
    const card = document.createElement('div');
    card.className = 'upload-card';
    card.dataset.area = def.key;
    card.innerHTML = `
      <div class="upload-card-head">
        <span class="order-circle${def.required ? ' order-circle-required' : ''}">${def.order}</span>
        <div class="upload-card-meta">
          <span class="upload-card-title">${escapeHtml(def.title)}</span>
          <span class="upload-card-area">${escapeHtml(def.short)} · ${escapeHtml(def.key)}</span>
          ${def.required ? '<span class="upload-card-required">* 필수 — 먼저 업로드</span>' : ''}
        </div>
      </div>
      <div class="dropzone" tabindex="0" role="button" aria-label="${escapeHtml(def.title)} 파일 선택 또는 드래그">
        <div class="dropzone-primary">클릭하여 파일 선택</div>
        <div class="dropzone-secondary">또는 .xls / .xlsx 파일을 드래그 · 최대 50MB</div>
      </div>
      <input type="file" class="file-input" accept=".xls,.xlsx" hidden>
      <div class="upload-card-actions">
        <span class="file-name" data-role="filename"></span>
        <button type="button" class="btn btn-secondary btn-sm" data-role="remove" hidden>제거</button>
      </div>
    `;
    grid.appendChild(card);

    const dz = card.querySelector('.dropzone');
    const fileInput = card.querySelector('.file-input');
    const removeBtn = card.querySelector('[data-role="remove"]');

    const handleFiles = (files) => {
      if (!files || !files.length) return;
      const file = files[0];
      handleUpload(def.key, file, card);
    };

    dz.addEventListener('click', () => fileInput.click());
    dz.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); fileInput.click(); }
    });
    dz.addEventListener('dragover', (e) => { e.preventDefault(); dz.classList.add('is-drag'); });
    dz.addEventListener('dragleave', () => dz.classList.remove('is-drag'));
    dz.addEventListener('drop', (e) => {
      e.preventDefault();
      dz.classList.remove('is-drag');
      handleFiles(e.dataTransfer.files);
    });
    fileInput.addEventListener('change', () => handleFiles(fileInput.files));

    removeBtn.addEventListener('click', () => {
      delete state.uploadedFiles[def.key];
      fileInput.value = '';
      setCardState(card, 'idle');
      card.querySelector('[data-role="filename"]').textContent = '';
      removeBtn.hidden = true;
      updateDbBuildButton();
    });
  });
}

function setCardState(card, stateName, text) {
  const dz = card.querySelector('.dropzone');
  dz.classList.remove('is-complete', 'is-error', 'is-drag');
  const primary = dz.querySelector('.dropzone-primary');
  const secondary = dz.querySelector('.dropzone-secondary');
  if (stateName === 'complete') {
    dz.classList.add('is-complete');
    primary.innerHTML = `<span class="dropzone-check">✓</span>업로드 완료`;
    if (text) secondary.textContent = text;
  } else if (stateName === 'error') {
    dz.classList.add('is-error');
    primary.textContent = '업로드 오류';
    secondary.textContent = text || '다시 시도해주세요.';
  } else if (stateName === 'uploading') {
    primary.textContent = '업로드 중…';
    secondary.textContent = text || '';
  } else {
    primary.textContent = '클릭하여 파일 선택';
    secondary.textContent = '또는 .xls / .xlsx 파일을 드래그 · 최대 50MB';
  }
}

async function handleUpload(area, file, card) {
  // 클라이언트 검증
  const name = (file.name || '').toLowerCase();
  const ext = name.includes('.') ? name.slice(name.lastIndexOf('.')) : '';
  if (!ALLOWED_EXTS.includes(ext)) {
    setCardState(card, 'error', 'XLS/XLSX 파일만 업로드 가능합니다.');
    showToast('XLS/XLSX 파일만 업로드 가능합니다.', 'error');
    return;
  }
  if (file.size > MAX_UPLOAD_BYTES) {
    setCardState(card, 'error', '파일 크기가 50MB를 초과합니다.');
    showToast('파일 크기 초과 (최대 50MB).', 'error');
    return;
  }

  setCardState(card, 'uploading', `${file.name} (${formatBytes(file.size)})`);
  try {
    const fd = new FormData();
    fd.append('file', file, file.name);
    fd.append('area', area);
    const res = await api('POST', API.UPLOAD, fd);
    state.uploadedFiles[area] = {
      file_id: res.file_id,
      filename: res.filename,
      size: res.size,
    };
    setCardState(card, 'complete', `${res.filename} · ${formatBytes(res.size)}`);
    card.querySelector('[data-role="filename"]').textContent = res.filename;
    card.querySelector('[data-role="remove"]').hidden = false;
    showToast(`${AREA_BY_KEY[area].short} 업로드 완료`, 'success', 2200);
    updateDbBuildButton();
  } catch (e) {
    setCardState(card, 'error', e.message || '업로드 실패');
    showToast(e.message || '업로드 실패', 'error');
  }
}

function updateDbBuildButton() {
  const btn = $('#btn-db-build');
  const hint = $('#db-build-hint');
  const hasRequired = !!state.uploadedFiles['subject_grades'];
  const dbExists = !!(state.dbStatus && state.dbStatus.exists);
  const uploadedCount = Object.keys(state.uploadedFiles).length;

  btn.disabled = !hasRequired;
  hint.classList.remove('is-ok', 'is-error');

  if (!hasRequired) {
    if (dbExists) {
      hint.textContent = `DB가 이미 구축되어 있습니다 (학생 ${state.dbStatus.students}명). 재구축하려면 교과성적을 업로드하세요.`;
    } else {
      hint.textContent = '교과성적(필수)을 먼저 업로드하세요.';
      hint.classList.add('is-error');
    }
  } else {
    hint.textContent = `업로드된 파일: ${uploadedCount}개 / 5개 — "DB 구축"을 눌러 진행하세요.`;
    hint.classList.add('is-ok');
  }
}

async function buildDatabase() {
  const btn = $('#btn-db-build');
  const spinner = btn.querySelector('.spinner');
  const label = btn.querySelector('.btn-label');

  const fileIds = {};
  for (const [area, info] of Object.entries(state.uploadedFiles)) {
    fileIds[area] = info.file_id;
  }
  if (!fileIds['subject_grades']) {
    showToast('교과성적 파일을 먼저 업로드하세요.', 'error');
    return;
  }

  btn.disabled = true;
  btn.setAttribute('aria-busy', 'true');
  spinner.hidden = false;
  label.textContent = 'DB 구축 중…';

  const resultBox = $('#db-build-result');
  resultBox.hidden = true;

  try {
    const res = await api('POST', API.DB_BUILD, { file_ids: fileIds });
    showToast('DB 구축 완료', 'success');
    resultBox.hidden = false;
    const perArea = res.records_per_area || {};
    const parts = AREA_DEFS.map(d => {
      const k = d.key;
      const n = perArea[k] || 0;
      return `${d.short} ${n.toLocaleString()}건`;
    });
    resultBox.innerHTML = `
      <strong>DB 구축 완료</strong> — 학생 ${(res.students || 0).toLocaleString()}명
      <div style="margin-top:6px;font-size:var(--text-xs);color:var(--text-2);">${parts.join(' · ')}</div>
    `;
    await refreshDbStatus();
    // 학생 조회 탭 캐시 리셋
    state.students = [];
    state.classesByGrade = {};
  } catch (e) {
    showToast(e.message || 'DB 구축 실패', 'error', 6000);
  } finally {
    spinner.hidden = true;
    label.textContent = 'DB 구축';
    btn.removeAttribute('aria-busy');
    updateDbBuildButton();
  }
}

async function resetDatabase() {
  if (!confirm('모든 학생 및 점검 데이터가 삭제됩니다. 계속하시겠습니까?')) return;
  const btn = $('#btn-db-reset');
  const spinner = btn.querySelector('.spinner');
  const label = btn.querySelector('.btn-label');
  btn.disabled = true;
  spinner.hidden = false;
  label.textContent = '초기화 중…';
  try {
    await api('POST', '/api/db/reset');
    state.uploadedFiles = {};
    state.students = [];
    state.classesByGrade = {};
    renderUploadCards();
    const resultBox = $('#db-build-result');
    resultBox.hidden = true;
    showToast('DB가 초기화되었습니다', 'success');
    await refreshDbStatus();
    updateDbBuildButton();
  } catch (e) {
    showToast(e.message || 'DB 초기화 실패', 'error', 6000);
  } finally {
    spinner.hidden = true;
    label.textContent = 'DB 초기화';
    btn.disabled = false;
  }
}

/* =============================================================
   탭 2: 학생 조회
   ============================================================= */
function buildClassOptions(grade) {
  const sel = $('#filter-class');
  sel.innerHTML = '<option value="">전체</option>';
  if (!grade) return;
  const classes = state.classesByGrade[grade] || [];
  classes.forEach((c) => {
    const opt = document.createElement('option');
    opt.value = c;
    opt.textContent = `${c}반`;
    sel.appendChild(opt);
  });
}

async function loadStudents() {
  const loading = $('#students-loading');
  const empty = $('#students-empty');
  const tbody = $('#students-tbody');
  const banner = $('#search-mode-banner');
  banner.hidden = true;

  loading.hidden = false;
  empty.hidden = true;
  tbody.innerHTML = '';

  try {
    const params = new URLSearchParams();
    const g = $('#filter-grade').value;
    const c = $('#filter-class').value;
    const n = $('#filter-name').value.trim();
    if (g) params.set('grade', g);
    if (c) params.set('class_no', c);
    if (n) params.set('name', n);
    const url = params.toString() ? `${API.STUDENTS}?${params}` : API.STUDENTS;
    const rows = await api('GET', url);
    state.students = Array.isArray(rows) ? rows : [];

    // class_no 캐시 업데이트 (전체 로딩시)
    if (!g && !c && !n) {
      const map = {};
      state.students.forEach((s) => {
        if (!map[s.grade]) map[s.grade] = new Set();
        map[s.grade].add(s.class_no);
      });
      state.classesByGrade = {};
      Object.keys(map).forEach((k) => {
        state.classesByGrade[k] = Array.from(map[k]).sort((a, b) => a - b);
      });
    }

    renderStudents(state.students);
  } catch (e) {
    showToast(e.message || '학생 목록 로드 실패', 'error');
  } finally {
    loading.hidden = true;
  }
}

function renderStudents(rows) {
  const tbody = $('#students-tbody');
  const empty = $('#students-empty');
  tbody.innerHTML = '';
  if (!rows.length) {
    empty.hidden = false;
    return;
  }
  empty.hidden = true;
  rows.forEach((s) => {
    const tr = document.createElement('tr');
    tr.dataset.studentId = s.id;
    const badgeFor = (area) => {
      const has = !!(s.areas && s.areas[area]);
      return has
        ? '<span class="badge badge-written">작성됨</span>'
        : '<span class="badge badge-empty">미작성</span>';
    };
    tr.innerHTML = `
      <td>${s.grade}학년</td>
      <td>${s.class_no}반</td>
      <td>${s.number}</td>
      <td>${escapeHtml(s.name)}</td>
      <td>${badgeFor('subject_details')}</td>
      <td>${badgeFor('creative_activities')}</td>
      <td>${badgeFor('volunteer_activities')}</td>
      <td>${badgeFor('behavior_opinion')}</td>
    `;
    tr.addEventListener('click', () => openStudentDetailModal(s.id));
    tbody.appendChild(tr);
  });
}

async function performKeywordSearch() {
  const keyword = $('#filter-keyword').value.trim();
  const banner = $('#search-mode-banner');
  if (!keyword) {
    banner.hidden = true;
    await loadStudents();
    return;
  }
  const loading = $('#students-loading');
  const empty = $('#students-empty');
  const tbody = $('#students-tbody');
  tbody.innerHTML = '';
  empty.hidden = true;
  loading.hidden = false;
  try {
    const params = new URLSearchParams({ keyword });
    const rows = await api('GET', `${API.SEARCH}?${params}`);
    banner.hidden = false;
    banner.textContent = `키워드 "${keyword}" 검색 결과 ${rows.length}건 — 행 클릭 시 해당 학생의 전체 상세를 봅니다.`;
    renderSearchResults(rows);
  } catch (e) {
    showToast(e.message || '검색 실패', 'error');
  } finally {
    loading.hidden = true;
  }
}

function renderSearchResults(rows) {
  const tbody = $('#students-tbody');
  const empty = $('#students-empty');
  tbody.innerHTML = '';
  if (!rows.length) { empty.hidden = false; return; }
  empty.hidden = true;

  // 헤더를 검색 결과용으로는 그대로 두되, 한 줄에 요약 정보를 담는다.
  rows.forEach((r) => {
    const tr = document.createElement('tr');
    tr.dataset.studentId = r.student_id;
    const areaLabel = AREA_BY_KEY[r.area] ? AREA_BY_KEY[r.area].short : r.area;
    tr.innerHTML = `
      <td>${r.grade}학년</td>
      <td>${r.class_no}반</td>
      <td>${r.number}</td>
      <td>${escapeHtml(r.student_name)}</td>
      <td colspan="4">
        <span class="badge badge-muted" style="margin-right:8px">${escapeHtml(areaLabel)}</span>
        <span style="color:var(--text-2);font-size:var(--text-sm)">${escapeHtml(truncate(r.snippet, 120))}</span>
      </td>
    `;
    tr.addEventListener('click', () => openStudentDetailModal(r.student_id, r.area));
    tbody.appendChild(tr);
  });
}

/* ---------- 학생 상세 모달 ---------- */
async function openStudentDetailModal(studentId, defaultArea) {
  try {
    const res = await api('GET', API.STUDENT_DETAILS(studentId));
    state.currentStudentDetail = res;
    const s = res.student;
    const title = `${s.grade}학년 ${s.class_no}반 ${s.number}번 ${s.name}`;
    const root = document.createElement('div');

    // 서브탭
    const subtabsEl = document.createElement('div');
    subtabsEl.className = 'subtabs';
    const contentEl = document.createElement('div');

    const availableAreas = AREA_DEFS.filter(d => {
      // 데이터가 없는 영역도 탭으로 보여주되 비어있으면 안내
      return true;
    });

    const recordsByArea = {};
    AREA_DEFS.forEach(d => { recordsByArea[d.key] = []; });
    (res.records || []).forEach(r => {
      if (!recordsByArea[r.area]) recordsByArea[r.area] = [];
      recordsByArea[r.area].push(r);
    });

    const renderArea = (areaKey) => {
      contentEl.innerHTML = '';
      const records = recordsByArea[areaKey] || [];
      if (!records.length) {
        contentEl.innerHTML = `<div class="empty-state" style="padding:var(--space-5)">해당 영역에 작성된 내용이 없습니다.</div>`;
        return;
      }
      records.forEach((r) => {
        const block = document.createElement('div');
        block.className = 'detail-block';
        const metaParts = [];
        if (r.grade_year) metaParts.push(`${r.grade_year}학년`);
        if (r.semester) metaParts.push(`${r.semester}학기`);
        if (r.subject) metaParts.push(escapeHtml(r.subject));
        if (r.extra && r.extra.hours !== undefined && r.extra.hours !== null) metaParts.push(`${r.extra.hours}시간`);
        if (r.extra && r.extra.date) metaParts.push(escapeHtml(r.extra.date));
        block.innerHTML = `
          <div class="detail-meta">${metaParts.join(' · ') || '-'}</div>
          <div class="detail-content">${escapeHtml(r.content || '')}</div>
        `;
        contentEl.appendChild(block);
      });
    };

    availableAreas.forEach((d, idx) => {
      const btn = document.createElement('button');
      btn.className = 'subtab';
      btn.type = 'button';
      btn.textContent = `${d.short} (${(recordsByArea[d.key] || []).length})`;
      btn.addEventListener('click', () => {
        subtabsEl.querySelectorAll('.subtab').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        renderArea(d.key);
      });
      subtabsEl.appendChild(btn);
      const initial = defaultArea ? (d.key === defaultArea) : (idx === 0);
      if (initial) {
        btn.classList.add('active');
      }
    });

    root.appendChild(subtabsEl);
    root.appendChild(contentEl);

    // 초기 영역 렌더
    const initialArea = defaultArea && recordsByArea[defaultArea] !== undefined ? defaultArea : AREA_DEFS[0].key;
    renderArea(initialArea);

    openModal(title, root);
  } catch (e) {
    showToast(e.message || '상세 조회 실패', 'error');
  }
}

/* =============================================================
   탭 3: AI 점검
   ============================================================= */
let promptLoadedOnce = false;

function setGeminiConnState(status) {
  const el = $('#gemini-conn-indicator');
  const txt = el.querySelector('.conn-text');
  el.classList.remove('conn-indicator-on', 'conn-indicator-off', 'conn-indicator-busy');
  if (status === 'connected') {
    el.classList.add('conn-indicator-on');
    txt.textContent = '연결됨';
    updateGeminiBadge('connected');
  } else if (status === 'connecting') {
    el.classList.add('conn-indicator-busy');
    txt.textContent = '연결 중…';
    updateGeminiBadge('connecting');
  } else {
    el.classList.add('conn-indicator-off');
    txt.textContent = '미연결';
    updateGeminiBadge('off');
  }
}

async function connectGemini() {
  const input = $('#api-key');
  const key = input.value.trim();
  if (!key) {
    showToast('API 키를 입력하세요.', 'error');
    return;
  }
  const btn = $('#btn-gemini-connect');
  btn.disabled = true;
  setGeminiConnState('connecting');
  try {
    const res = await api('POST', API.GEMINI_CONNECT, { api_key: key });
    state.apiKey = key; // 메모리에만
    state.availableModels = res.models || [];
    setGeminiConnState('connected');
    populateModelSelect();
    showToast('Gemini 연결 성공', 'success');
    updateInspectButton();
  } catch (e) {
    setGeminiConnState('off');
    state.apiKey = null;
    showToast(e.message || 'Gemini 연결 실패', 'error', 5500);
  } finally {
    btn.disabled = false;
  }
}

function populateModelSelect() {
  const sel = $('#model-select');
  sel.innerHTML = '';
  if (!state.availableModels.length) {
    const opt = document.createElement('option');
    opt.value = '';
    opt.textContent = '사용 가능한 모델 없음';
    sel.appendChild(opt);
    sel.disabled = true;
    return;
  }
  sel.disabled = false;
  // Gemini API는 "models/gemini-2.5-flash-..." 형태로 반환하므로 부분 문자열로 비교
  const preferredKeywords = ['gemini-2.5-flash-preview', 'gemini-2.5-flash', 'gemini-2.5-pro', 'gemini-2.0-flash'];
  const isPreferred = (m) => preferredKeywords.some(kw => m.includes(kw));
  const ordered = [
    ...state.availableModels.filter(m => isPreferred(m)),
    ...state.availableModels.filter(m => !isPreferred(m)),
  ];
  ordered.forEach((m, i) => {
    const opt = document.createElement('option');
    opt.value = m;
    // "models/" prefix 제거해 표시
    opt.textContent = m.replace(/^models\//, '');
    if (i === 0) opt.selected = true;
    sel.appendChild(opt);
  });
}

async function refreshPromptIfNeeded() {
  if (promptLoadedOnce) return;
  await loadPrompt();
}

async function loadPrompt() {
  try {
    const res = await api('GET', API.PROMPT);
    $('#prompt-textarea').value = res.prompt_text || '';
    $('#prompt-updated').textContent = res.updated_at ? `갱신: ${formatDateTime(res.updated_at)}` : '';
    promptLoadedOnce = true;
  } catch (e) {
    showToast(e.message || '프롬프트 로드 실패', 'error');
  }
}

async function resetPrompt() {
  if (!confirm('프롬프트를 기본값으로 복원합니다. 현재 편집 중인 내용은 사라집니다. 계속하시겠습니까?')) return;
  try {
    const res = await api('POST', API.PROMPT_RESET);
    $('#prompt-textarea').value = res.prompt_text || '';
    $('#prompt-updated').textContent = res.updated_at ? `갱신: ${formatDateTime(res.updated_at)}` : '';
    showToast('프롬프트를 기본값으로 복원했습니다.', 'success');
  } catch (e) {
    showToast(e.message || '복원 실패', 'error');
  }
}

async function savePrompt() {
  const text = $('#prompt-textarea').value;
  if (!text.trim()) {
    showToast('프롬프트가 비어 있습니다.', 'error');
    return;
  }
  try {
    const res = await api('PUT', API.PROMPT, { prompt_text: text });
    $('#prompt-updated').textContent = res.updated_at ? `갱신: ${formatDateTime(res.updated_at)}` : '';
    showToast('프롬프트 저장 완료', 'success');
  } catch (e) {
    showToast(e.message || '프롬프트 저장 실패', 'error');
  }
}

function selectedAreas() {
  return $$('.area-check').filter(c => c.checked).map(c => c.value);
}

function updateInspectButton() {
  const btn = $('#btn-inspect-start');
  const ready = !!state.apiKey && selectedAreas().length > 0 && !state.currentInspectionId;
  btn.disabled = !ready;
}

async function startInspection() {
  if (state.currentInspectionId) {
    showToast('이미 진행 중인 검사가 있습니다.', 'error');
    return;
  }
  if (!state.apiKey) {
    showToast('먼저 Gemini에 연결하세요.', 'error');
    return;
  }
  const areas = selectedAreas();
  if (!areas.length) {
    showToast('점검 영역을 1개 이상 선택하세요.', 'error');
    return;
  }
  const model = $('#model-select').value;
  if (!model) {
    showToast('모델을 선택하세요.', 'error');
    return;
  }
  const batch = parseInt($('#batch-size').value, 10) || 3;
  const grade = $('#inspect-grade').value ? parseInt($('#inspect-grade').value, 10) : null;
  const classNo = $('#inspect-class').value ? parseInt($('#inspect-class').value, 10) : null;

  const body = {
    areas,
    model,
    batch_size: Math.min(Math.max(batch, 1), 5),
    grade,
    class_no: classNo,
  };

  // UI 리셋
  state.inspectionResults = [];
  state.liveViolations = 0;
  $('#live-tbody').innerHTML = '';
  $('#live-empty').hidden = false;
  $('#live-count').textContent = '0건';
  $('#progress-card').hidden = false;
  setProgress(0, 0);
  setProgressStatus('시작 중…');
  $('#progress-current').textContent = '';
  $('#progress-fill').classList.remove('is-done');

  const startBtn = $('#btn-inspect-start');
  const cancelBtn = $('#btn-inspect-cancel');
  startBtn.disabled = true;
  startBtn.setAttribute('aria-busy', 'true');

  try {
    const res = await api('POST', API.INSPECT_START, body);
    const inspectionId = res.inspection_id;
    state.currentInspectionId = inspectionId;
    cancelBtn.hidden = false;
    openInspectionStream(inspectionId);
    setProgressStatus('검사 진행 중');
    showToast('검사를 시작했습니다.', 'info', 2200);
  } catch (e) {
    showToast(e.message || '검사 시작 실패', 'error', 5500);
    setProgressStatus('시작 실패');
    startBtn.removeAttribute('aria-busy');
    updateInspectButton();
  }
}

function openInspectionStream(inspectionId) {
  if (state.eventSource) {
    try { state.eventSource.close(); } catch {}
  }
  const es = new EventSource(API.INSPECT_STREAM(inspectionId));
  state.eventSource = es;

  es.addEventListener('progress', (ev) => {
    try {
      const d = JSON.parse(ev.data);
      setProgress(d.processed, d.total);
      const parts = [];
      if (d.current_student) {
        const areaShort = d.current_area && AREA_BY_KEY[d.current_area] ? AREA_BY_KEY[d.current_area].short : (d.current_area || '');
        parts.push(`현재: ${d.current_student}${areaShort ? ` · ${areaShort}` : ''}`);
      }
      if (d.eta_sec !== null && d.eta_sec !== undefined && d.processed < d.total) {
        parts.push(`남은 시간: 약 ${formatDuration(d.eta_sec)}`);
      }
      if (parts.length) {
        $('#progress-current').textContent = parts.join(' · ');
      }
    } catch {}
  });

  es.addEventListener('result', (ev) => {
    try {
      const r = JSON.parse(ev.data);
      state.inspectionResults.push(r);
      if (r.violation) {
        state.liveViolations += 1;
        appendLiveResultRow(r);
      }
    } catch {}
  });

  es.addEventListener('done', (ev) => {
    // EventSource 의 자동 재연결을 막기 위해 가장 먼저 close.
    try { es.close(); } catch {}
    state.eventSource = null;
    try {
      const d = JSON.parse(ev.data);
      showInspectionSummary(d);
    } catch {}
    finishInspection();
  });

  es.addEventListener('error', (ev) => {
    // 서버 커스텀 error 이벤트 or 네트워크 오류
    if (ev && ev.data) {
      try {
        const err = JSON.parse(ev.data);
        showToast(err.message || '점검 중 오류가 발생했습니다.', 'error');
      } catch {
        showToast('점검 중 오류가 발생했습니다.', 'error');
      }
    } else {
      // 네트워크 레벨 오류: readyState로 구분
      if (es.readyState === EventSource.CLOSED) {
        // 이미 종료됨 (done 후에도 호출될 수 있음) — 조용히 처리
      } else {
        showToast('서버 스트림 연결이 끊겼습니다.', 'error');
      }
    }
  });
}

function setProgress(processed, total) {
  const pct = total > 0 ? Math.min(100, Math.round((processed / total) * 100)) : 0;
  $('#progress-fill').style.width = `${pct}%`;
  $('#progress-text').textContent = `${processed.toLocaleString()} / ${total.toLocaleString()}건`;
  if (total > 0 && processed >= total) {
    $('#progress-fill').classList.add('is-done');
  }
}

function setProgressStatus(s) {
  $('#progress-status').textContent = s;
}

function appendLiveResultRow(r) {
  const tbody = $('#live-tbody');
  $('#live-empty').hidden = true;
  const areaShort = AREA_BY_KEY[r.area] ? AREA_BY_KEY[r.area].short : r.area;
  const tr = document.createElement('tr');
  tr.classList.add('result-row-new');
  tr.innerHTML = `
    <td>${r.grade}-${r.class_no}-${r.number}</td>
    <td>${escapeHtml(r.student_name)}</td>
    <td><span class="badge badge-muted">${escapeHtml(areaShort)}</span></td>
    <td><span class="badge badge-violation">${escapeHtml(r.category || '위반')}</span></td>
    <td>${escapeHtml(truncate(r.reason || r.evidence || '', 120))}</td>
  `;
  tr.addEventListener('click', () => openResultDetailModal(r));
  tbody.prepend(tr);
  $('#live-count').textContent = `${state.liveViolations}건`;
}

function showInspectionSummary(d) {
  setProgressStatus('검사 완료');
  const violations = d.total_violations || 0;
  const normals = d.total_normal || 0;
  const duration = d.duration_sec || 0;
  const pc = $('#progress-current');
  pc.innerHTML = `완료 — 위반 <strong style="color:var(--danger)">${violations}건</strong> / 정상 <strong>${normals}건</strong> / 소요 ${duration.toFixed(1)}초`;
  showToast(`검사 완료: 위반 ${violations}건, 정상 ${normals}건`, 'success', 5000);
  // 결과 탭에서 해당 inspection을 표시하도록 id 기억
  if (d.inspection_id) {
    state.selectedInspectionId = d.inspection_id;
  }
}

async function cancelInspection() {
  if (!state.currentInspectionId) return;
  const id = state.currentInspectionId;
  try {
    await api('POST', API.INSPECT_CANCEL(id));
    showToast('검사 취소 요청을 보냈습니다.', 'info');
    setProgressStatus('취소 요청됨');
  } catch (e) {
    showToast(e.message || '취소 실패', 'error');
  }
}

function finishInspection() {
  state.currentInspectionId = null;
  if (state.eventSource) {
    try { state.eventSource.close(); } catch {}
    state.eventSource = null;
  }
  $('#btn-inspect-cancel').hidden = true;
  const sb = $('#btn-inspect-start');
  sb.removeAttribute('aria-busy');
  updateInspectButton();
}

/* =============================================================
   탭 4: 결과 확인
   ============================================================= */
async function loadInspections() {
  try {
    const rows = await api('GET', API.INSPECTIONS);
    state.inspectionHistory = Array.isArray(rows) ? rows : [];
    renderInspectionSelect();
    if (state.inspectionHistory.length) {
      const target = state.selectedInspectionId && state.inspectionHistory.find(i => i.id === state.selectedInspectionId)
        ? state.selectedInspectionId
        : state.inspectionHistory[0].id;
      state.selectedInspectionId = target;
      $('#inspection-select').value = String(target);
      await loadResults();
    } else {
      renderResultsEmpty();
    }
  } catch (e) {
    showToast(e.message || '검사 이력 로드 실패', 'error');
  }
}

function renderInspectionSelect() {
  const sel = $('#inspection-select');
  sel.innerHTML = '';
  if (!state.inspectionHistory.length) {
    const opt = document.createElement('option');
    opt.value = '';
    opt.textContent = '검사 이력이 없습니다';
    sel.appendChild(opt);
    $('#btn-results-export').disabled = true;
    return;
  }
  state.inspectionHistory.forEach((i) => {
    const opt = document.createElement('option');
    opt.value = String(i.id);
    const statusLabel = i.status === 'done' ? '완료'
                     : i.status === 'running' ? '진행중'
                     : i.status === 'cancelled' ? '취소'
                     : i.status === 'error' ? '오류' : i.status;
    opt.textContent = `#${i.id} · ${formatDateTime(i.started_at)} · ${i.model} · ${statusLabel} (위반 ${i.violations}/${i.total_records})`;
    sel.appendChild(opt);
  });
  $('#btn-results-export').disabled = false;
}

function renderResultsEmpty() {
  $('#results-tbody').innerHTML = '';
  $('#results-empty').hidden = false;
  $('#result-summary').hidden = true;
  $('#btn-results-export').disabled = true;
}

async function loadResults() {
  const id = state.selectedInspectionId;
  if (!id) { renderResultsEmpty(); return; }
  const filter = state.resultFilter || 'all';
  const loading = $('#results-loading');
  const empty = $('#results-empty');
  const tbody = $('#results-tbody');
  loading.hidden = false;
  empty.hidden = true;
  tbody.innerHTML = '';

  try {
    const params = new URLSearchParams({ inspection_id: String(id) });
    if (filter !== 'all') params.set('filter', filter);
    const rows = await api('GET', `${API.RESULTS}?${params}`);
    renderResults(Array.isArray(rows) ? rows : []);
    renderResultSummary(id, rows);
  } catch (e) {
    showToast(e.message || '결과 조회 실패', 'error');
    empty.hidden = false;
  } finally {
    loading.hidden = true;
  }
}

function renderResults(rows) {
  const tbody = $('#results-tbody');
  const empty = $('#results-empty');
  tbody.innerHTML = '';
  if (!rows.length) { empty.hidden = false; return; }
  empty.hidden = true;
  rows.forEach((r) => {
    const tr = document.createElement('tr');
    const areaShort = AREA_BY_KEY[r.area] ? AREA_BY_KEY[r.area].short : r.area;
    const violationCell = r.violation
      ? `<span class="badge badge-violation">위반</span>`
      : `<span class="badge badge-normal">정상</span>`;
    tr.innerHTML = `
      <td>${escapeHtml(r.student_name)}</td>
      <td>${r.grade}-${r.class_no}-${r.number}</td>
      <td>${escapeHtml(areaShort)}</td>
      <td>${violationCell}</td>
      <td>${escapeHtml(r.category || '-')}</td>
      <td style="color:var(--text-2)">${escapeHtml(truncate(r.reason || r.evidence || '', 100))}</td>
    `;
    tr.addEventListener('click', () => openResultDetailModal(r));
    tbody.appendChild(tr);
  });
  $('#btn-results-export').disabled = false;
}

function renderResultSummary(inspectionId, rows) {
  const banner = $('#result-summary');
  const meta = state.inspectionHistory.find(i => i.id === inspectionId);
  if (!meta && !rows.length) { banner.hidden = true; return; }

  let violations = 0;
  let normals = 0;
  (rows || []).forEach(r => { if (r.violation) violations += 1; else normals += 1; });

  // 필터 중이라면 rows 기반 집계가 전체와 다를 수 있음 -> meta 우선 사용
  if (meta) {
    const totalRecords = meta.total_records || 0;
    const violMeta = meta.violations || 0;
    const normalsMeta = Math.max(0, totalRecords - violMeta);
    $('#summary-violations').textContent = violMeta.toLocaleString();
    $('#summary-normals').textContent = normalsMeta.toLocaleString();
    $('#summary-total').textContent = totalRecords.toLocaleString();
    $('#summary-model').textContent = meta.model || '-';
    $('#summary-started').textContent = formatDateTime(meta.started_at);
  } else {
    $('#summary-violations').textContent = violations.toLocaleString();
    $('#summary-normals').textContent = normals.toLocaleString();
    $('#summary-total').textContent = (violations + normals).toLocaleString();
    $('#summary-model').textContent = '-';
    $('#summary-started').textContent = '-';
  }
  banner.hidden = false;
}

function openResultDetailModal(r) {
  const areaShort = AREA_BY_KEY[r.area] ? AREA_BY_KEY[r.area].short : r.area;
  const title = `${r.grade}-${r.class_no}-${r.number} ${r.student_name || ''} · ${areaShort}`;
  const wrapper = document.createElement('div');
  const suggestedBlock = r.suggested_text
    ? `<div class="detail-block">
        <h4>수정 제안</h4>
        <div class="detail-content detail-suggested">${escapeHtml(r.suggested_text)}</div>
      </div>`
    : '';
  wrapper.innerHTML = `
    <div class="detail-block">
      <h4>판정</h4>
      <div>${r.violation ? '<span class="badge badge-violation">위반</span>' : '<span class="badge badge-normal">정상</span>'}
      ${r.category ? `<span class="badge badge-muted" style="margin-left:6px">${escapeHtml(r.category)}</span>` : ''}</div>
    </div>
    <div class="detail-block">
      <h4>AI 판단 근거 (사유)</h4>
      <div class="detail-content">${escapeHtml(r.reason || '(없음)')}</div>
    </div>
    <div class="detail-block">
      <h4>위반 발췌</h4>
      <div class="detail-content">${escapeHtml(r.evidence || '(없음)')}</div>
    </div>
    ${suggestedBlock}
    ${r.processed_at ? `<div class="detail-meta">처리 시각: ${formatDateTime(r.processed_at)}</div>` : ''}
  `;
  openModal(title, wrapper);
}

async function exportResults() {
  const id = state.selectedInspectionId;
  if (!id) { showToast('내보낼 검사를 선택하세요.', 'error'); return; }
  const filter = state.resultFilter || 'all';
  const btn = $('#btn-results-export');
  btn.disabled = true;
  btn.setAttribute('aria-busy', 'true');
  try {
    const params = new URLSearchParams({ inspection_id: String(id), filter });
    const res = await fetch(`${API.RESULTS_EXPORT}?${params}`);
    if (!res.ok) {
      let msg = `내보내기 실패 (HTTP ${res.status})`;
      try { const j = await res.json(); if (j.detail) msg = j.detail; } catch {}
      throw new Error(msg);
    }
    const blob = await res.blob();
    // 파일명 추출 (RFC 5987 filename*= UTF-8''... 처리)
    const disp = res.headers.get('content-disposition') || '';
    let filename = `생기부점검결과_${id}.xlsx`;
    const m = disp.match(/filename\*=UTF-8''([^;]+)/i);
    if (m) {
      try { filename = decodeURIComponent(m[1]); } catch {}
    } else {
      const m2 = disp.match(/filename="?([^"]+)"?/i);
      if (m2) filename = m2[1];
    }
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
    showToast('Excel 다운로드 완료', 'success');
  } catch (e) {
    showToast(e.message || 'Excel 다운로드 실패', 'error');
  } finally {
    btn.disabled = false;
    btn.removeAttribute('aria-busy');
  }
}

/* =============================================================
   이벤트 바인딩
   ============================================================= */
function bindEvents() {
  // 업로드
  renderUploadCards();
  $('#btn-db-build').addEventListener('click', buildDatabase);
  $('#btn-db-reset').addEventListener('click', resetDatabase);

  // 학생 조회
  $('#btn-search').addEventListener('click', () => {
    const kw = $('#filter-keyword').value.trim();
    if (kw) performKeywordSearch();
    else loadStudents();
  });
  $('#btn-search-reset').addEventListener('click', () => {
    $('#filter-grade').value = '';
    $('#filter-class').innerHTML = '<option value="">전체</option>';
    $('#filter-name').value = '';
    $('#filter-keyword').value = '';
    loadStudents();
  });
  $('#filter-grade').addEventListener('change', () => {
    buildClassOptions($('#filter-grade').value);
  });
  $('#filter-name').addEventListener('keydown', (e) => { if (e.key === 'Enter') loadStudents(); });
  $('#filter-keyword').addEventListener('keydown', (e) => { if (e.key === 'Enter') performKeywordSearch(); });

  // 점검
  $('#btn-gemini-connect').addEventListener('click', connectGemini);
  $('#api-key').addEventListener('keydown', (e) => { if (e.key === 'Enter') connectGemini(); });
  $$('.area-check').forEach(c => c.addEventListener('change', updateInspectButton));
  $('#btn-prompt-toggle').addEventListener('click', () => {
    const body = $('#prompt-body');
    const toggle = $('#btn-prompt-toggle');
    const open = body.hidden;
    body.hidden = !open;
    toggle.setAttribute('aria-expanded', String(open));
    if (open) loadPrompt();
  });
  $('#btn-prompt-save').addEventListener('click', savePrompt);
  $('#btn-prompt-reload').addEventListener('click', loadPrompt);
  $('#btn-prompt-reset').addEventListener('click', resetPrompt);
  $('#btn-inspect-start').addEventListener('click', startInspection);
  $('#btn-inspect-cancel').addEventListener('click', cancelInspection);

  // 결과
  $('#inspection-select').addEventListener('change', (e) => {
    const v = parseInt(e.target.value, 10);
    state.selectedInspectionId = isNaN(v) ? null : v;
    loadResults();
  });
  $('#result-filter-group').addEventListener('change', (e) => {
    if (e.target.name === 'result-filter') {
      state.resultFilter = e.target.value;
      loadResults();
    }
  });
  $('#btn-results-reload').addEventListener('click', loadResults);
  $('#btn-results-export').addEventListener('click', exportResults);

  // 모달 공용
  $('#modal-close').addEventListener('click', closeModal);
  $('#modal-overlay').addEventListener('click', (e) => {
    if (e.target === e.currentTarget) closeModal();
  });
  window.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && !$('#modal-overlay').hidden) closeModal();
  });

  // 페이지 이탈 시 SSE 정리
  window.addEventListener('beforeunload', () => {
    if (state.eventSource) { try { state.eventSource.close(); } catch {} }
  });
}

/* =============================================================
   테마 (다크/라이트)
   ============================================================= */
function applyTheme(theme) {
  document.documentElement.setAttribute('data-theme', theme);
  localStorage.setItem('theme', theme);
}

function toggleTheme() {
  const current = document.documentElement.getAttribute('data-theme') || 'light';
  applyTheme(current === 'dark' ? 'light' : 'dark');
}

/* =============================================================
   통합검사 탭
   ============================================================= */
const AREA_LABELS = {
  subject_details: '세부능력및특기사항',
  creative_activities: '창의적체험활동',
  volunteer_activities: '봉사활동상황',
  behavior_opinion: '행동특성및종합의견',
};

let validateTabInited = false;

async function initValidateTab() {
  if (validateTabInited) return;
  validateTabInited = true;
  await Promise.all([loadRulesList(), checkOllamaStatus()]);
  bindValidateEvents();
}

/* ---------- 규칙 파일 목록 ---------- */
async function loadRulesList() {
  try {
    const data = await api('GET', '/api/validate/rules/list');
    const years = [...new Set([
      ...data.violations.map(v => v.year),
      ...data.limits.map(l => l.year),
    ])].sort((a, b) => b - a);

    ['chars-year', 'rules-year'].forEach(id => {
      const sel = document.getElementById(id);
      if (!sel) return;
      sel.innerHTML = years.length
        ? years.map(y => `<option value="${y}">${y}</option>`).join('')
        : '<option value="2025">2025</option>';
    });

    const info = document.getElementById('rules-list-info');
    if (info) {
      const violLines = data.violations.map(v =>
        `<strong>${v.year}년</strong> 위반 규칙 ${v.pattern_count}개 (${v.updated})`
      ).join(' · ') || '없음';
      const limLines = data.limits.map(l =>
        `<strong>${l.year}년</strong> 글자수 한도 (${l.updated})`
      ).join(' · ') || '없음';
      info.innerHTML = `위반 규칙: ${violLines} &nbsp;|&nbsp; 글자수 한도: ${limLines}`;
    }
  } catch (e) {
    const info = document.getElementById('rules-list-info');
    if (info) info.textContent = '규칙 파일 정보를 불러올 수 없습니다.';
  }
}

/* ---------- Ollama 상태 ---------- */
async function checkOllamaStatus() {
  const statusEl = document.getElementById('ollama-status-text');
  const modelSel = document.getElementById('spacing-model');
  const runBtn = document.getElementById('btn-spacing-run');
  try {
    const data = await api('GET', '/api/validate/ollama/status');
    if (data.available) {
      if (statusEl) { statusEl.textContent = `Ollama 연결됨 (모델 ${data.models.length}개)`; statusEl.style.color = 'var(--success)'; }
      if (modelSel) {
        modelSel.innerHTML = data.models.map(m => `<option value="${m}">${m}</option>`).join('');
      }
      if (runBtn) runBtn.disabled = false;
    } else {
      if (statusEl) { statusEl.textContent = 'Ollama 미연결 — ollama serve 실행 후 탭을 다시 열어주세요'; statusEl.style.color = 'var(--danger)'; }
    }
  } catch {
    if (statusEl) { statusEl.textContent = 'Ollama 상태 확인 실패'; statusEl.style.color = 'var(--danger)'; }
  }
}

/* ---------- 이벤트 바인딩 ---------- */
function bindValidateEvents() {
  // 유사도 슬라이더 라벨
  const slider = document.getElementById('dup-threshold');
  const sliderLabel = document.getElementById('dup-threshold-label');
  if (slider && sliderLabel) {
    slider.addEventListener('input', () => { sliderLabel.textContent = slider.value + '%'; });
  }

  document.getElementById('btn-chars-run')?.addEventListener('click', runCharsCheck);
  document.getElementById('btn-rules-run')?.addEventListener('click', runRulesCheck);
  document.getElementById('btn-dup-run')?.addEventListener('click', runDupCheck);
  document.getElementById('btn-spacing-run')?.addEventListener('click', runSpacingCheck);
  document.getElementById('btn-rules-update')?.addEventListener('click', runRulesUpdate);
}

/* ---------- 공용 유틸 ---------- */
function setBtnLoading(btn, loading, label) {
  if (!btn) return;
  btn.disabled = loading;
  btn.innerHTML = loading
    ? '<span class="spinner"></span> 검사 중…'
    : label;
}

function showValidateResult(containerId, html) {
  const el = document.getElementById(containerId);
  if (!el) return;
  el.innerHTML = html;
  el.hidden = false;
}

function gradeClassParams(gradeId, classId) {
  const grade = document.getElementById(gradeId)?.value;
  const cls   = document.getElementById(classId)?.value;
  return { grade: grade ? parseInt(grade) : null, class_no: cls ? parseInt(cls) : null };
}

/* ---------- ① 글자수 검증 ---------- */
async function runCharsCheck() {
  const btn = document.getElementById('btn-chars-run');
  setBtnLoading(btn, true, '검증 시작');
  try {
    const year = parseInt(document.getElementById('chars-year')?.value || '2025');
    const { grade, class_no } = gradeClassParams('chars-grade', 'chars-class');
    const data = await api('POST', '/api/validate/chars', { year, grade, class_no });

    const overRows = data.results.filter(r => r.is_over);
    const html = `
      <div class="validate-summary">
        <span class="validate-chip">전체 ${data.total}건</span>
        <span class="validate-chip ${overRows.length ? 'validate-chip-danger' : 'validate-chip-ok'}">초과 ${overRows.length}건</span>
        <span class="validate-chip validate-chip-ok">정상 ${data.total - overRows.length}건</span>
      </div>
      <div class="table-wrap">
        <table class="data-table">
          <thead><tr>
            <th>학년</th><th>반</th><th>번</th><th>이름</th>
            <th>영역</th><th>과목/항목</th>
            <th>글자수</th><th>한도</th><th>초과</th>
          </tr></thead>
          <tbody>
          ${data.results.filter(r => r.is_over).map(r => `
            <tr>
              <td>${r.grade}</td><td>${r.class_no}</td><td>${r.number}</td>
              <td>${escapeHtml(r.student_name)}</td>
              <td>${escapeHtml(r.area_label)}</td>
              <td>${escapeHtml(r.subject || '')}</td>
              <td>${r.char_count.toLocaleString()}</td>
              <td>${r.char_limit != null ? r.char_limit.toLocaleString() : '-'}</td>
              <td><span class="badge badge-violation">+${r.char_over}</span></td>
            </tr>`).join('') || '<tr><td colspan="9" class="empty-state">초과 항목 없음 ✓</td></tr>'}
          </tbody>
        </table>
      </div>`;
    showValidateResult('chars-result', html);
  } catch (e) {
    showToast(`글자수 검증 실패: ${e.message}`, 'error');
  } finally {
    setBtnLoading(btn, false, '검증 시작');
  }
}

/* ---------- ② 로컬 규칙 검사 ---------- */
async function runRulesCheck() {
  const btn = document.getElementById('btn-rules-run');
  setBtnLoading(btn, true, '검사 시작');
  try {
    const year = parseInt(document.getElementById('rules-year')?.value || '2025');
    const { grade, class_no } = gradeClassParams('rules-grade', 'rules-class');
    const areas = Array.from(document.querySelectorAll('input[name="rules-area"]:checked')).map(c => c.value);
    if (!areas.length) { showToast('영역을 1개 이상 선택하세요', 'error'); return; }

    const data = await api('POST', '/api/validate/rules', { year, areas, grade, class_no });

    const violRows = data.results.filter(r => r.violation);
    const html = `
      <div class="validate-summary">
        <span class="validate-chip">전체 ${data.total}건</span>
        <span class="validate-chip ${violRows.length ? 'validate-chip-danger' : 'validate-chip-ok'}">위반 ${data.violations}건</span>
        <span class="validate-chip validate-chip-ok">정상 ${data.total - data.violations}건</span>
      </div>
      <div class="table-wrap">
        <table class="data-table">
          <thead><tr>
            <th>학년</th><th>반</th><th>번</th><th>이름</th>
            <th>영역</th><th>과목</th><th>위반 유형</th><th>발견 내용</th>
          </tr></thead>
          <tbody>
          ${violRows.map(r => r.hits.map(h => `
            <tr>
              <td>${r.grade}</td><td>${r.class_no}</td><td>${r.number}</td>
              <td>${escapeHtml(r.student_name)}</td>
              <td>${escapeHtml(r.area_label)}</td>
              <td>${escapeHtml(r.label || '')}</td>
              <td><span class="badge ${h.severity === 'high' ? 'badge-violation' : 'badge-running'}">${escapeHtml(h.type)}</span></td>
              <td>${escapeHtml(h.evidence)}</td>
            </tr>`).join('')).join('') || '<tr><td colspan="8" class="empty-state">위반 항목 없음 ✓</td></tr>'}
          </tbody>
        </table>
      </div>`;
    showValidateResult('rules-result', html);
  } catch (e) {
    showToast(`규칙 검사 실패: ${e.message}`, 'error');
  } finally {
    setBtnLoading(btn, false, '검사 시작');
  }
}

/* ---------- ③ 중복문장 검사 ---------- */
async function runDupCheck() {
  const btn = document.getElementById('btn-dup-run');
  setBtnLoading(btn, true, '검사 시작');
  try {
    const threshold = parseInt(document.getElementById('dup-threshold')?.value || '70') / 100;
    const grade = document.getElementById('dup-grade')?.value;
    const cross = document.getElementById('dup-cross')?.checked ?? true;
    const within = document.getElementById('dup-within')?.checked ?? true;
    const data = await api('POST', '/api/validate/duplicates', {
      grade: grade ? parseInt(grade) : null,
      threshold, cross_student: cross, within_student: within,
    });

    const html = `
      <div class="validate-summary">
        <span class="validate-chip">검사 레코드 ${data.total_records}건</span>
        <span class="validate-chip ${data.pairs.length ? 'validate-chip-danger' : 'validate-chip-ok'}">유사 쌍 ${data.pairs.length}건</span>
      </div>
      ${data.pairs.map(p => {
        const sim = Math.round(p.similarity * 100);
        const isHigh = sim >= 85;
        const typeTag = p.same_student ? '<span class="badge badge-running">학생 내부</span>' : '<span class="badge badge-violation">학생 간</span>';
        return `<div class="dup-pair">
          <div class="dup-pair-header">
            <span class="dup-sim-badge ${isHigh ? 'high' : ''}">유사도 ${sim}%</span>
            ${typeTag}
            <span class="badge badge-muted">${escapeHtml(p.area_label)}</span>
          </div>
          ${p.common_excerpt ? `<div class="dup-excerpt">공통 발췌: "${escapeHtml(p.common_excerpt)}"</div>` : ''}
          <div class="dup-students" style="margin-top:var(--space-3);">
            <div class="dup-student">
              <strong>${p.record_a.grade}-${p.record_a.class_no}-${p.record_a.number} ${escapeHtml(p.record_a.student_name)}</strong>
              ${p.record_a.label ? `<span class="muted">${escapeHtml(p.record_a.label)}</span>` : ''}
            </div>
            <div class="dup-student">
              <strong>${p.record_b.grade}-${p.record_b.class_no}-${p.record_b.number} ${escapeHtml(p.record_b.student_name)}</strong>
              ${p.record_b.label ? `<span class="muted">${escapeHtml(p.record_b.label)}</span>` : ''}
            </div>
          </div>
        </div>`;
      }).join('') || '<div class="empty-state">중복 문장 없음 ✓</div>'}`;
    showValidateResult('dup-result', html);
  } catch (e) {
    showToast(`중복 검사 실패: ${e.message}`, 'error');
  } finally {
    setBtnLoading(btn, false, '검사 시작');
  }
}

/* ---------- ④ 띄어쓰기 검사 ---------- */
async function runSpacingCheck() {
  const btn = document.getElementById('btn-spacing-run');
  const model = document.getElementById('spacing-model')?.value;
  if (!model) { showToast('Ollama 모델을 선택하세요', 'error'); return; }
  setBtnLoading(btn, true, '검사 시작');
  try {
    const { grade, class_no } = gradeClassParams('spacing-grade', 'spacing-class');
    const areas = Array.from(document.querySelectorAll('input[name="spacing-area"]:checked')).map(c => c.value);
    if (!areas.length) { showToast('영역을 1개 이상 선택하세요', 'error'); return; }

    const data = await api('POST', '/api/validate/spacing', { model, grade, class_no, areas });

    const withErrors = data.results.filter(r => r.error_count > 0);
    const html = `
      <div class="validate-summary">
        <span class="validate-chip">검사 ${data.total_records}건</span>
        <span class="validate-chip ${data.total_errors ? 'validate-chip-danger' : 'validate-chip-ok'}">오류 ${data.total_errors}개</span>
        <span class="validate-chip validate-chip-warn">모델: ${escapeHtml(model)}</span>
      </div>
      ${withErrors.map(r => `
        <div class="spacing-card">
          <div class="spacing-card-header">
            <strong>${r.grade}-${r.class_no}-${r.number} ${escapeHtml(r.student_name)}</strong>
            <span class="badge badge-muted">${escapeHtml(r.area_label)}</span>
            ${r.label ? `<span class="badge badge-muted">${escapeHtml(r.label)}</span>` : ''}
            <span class="badge badge-violation">오류 ${r.error_count}개</span>
          </div>
          <div class="spacing-diff">
            ${r.errors.map(e => `
              <div style="margin-bottom:6px;">
                <del>${escapeHtml(e.wrong)}</del> → <ins>${escapeHtml(e.correct)}</ins>
                ${e.context ? `<span class="muted" style="font-size:var(--text-xs);margin-left:8px;">(…${escapeHtml(e.context)}…)</span>` : ''}
              </div>`).join('')}
          </div>
        </div>`).join('') || '<div class="empty-state">띄어쓰기 오류 없음 ✓</div>'}`;
    showValidateResult('spacing-result', html);
  } catch (e) {
    showToast(`띄어쓰기 검사 실패: ${e.message}`, 'error');
  } finally {
    setBtnLoading(btn, false, '검사 시작');
  }
}

/* ---------- ⑤ 규칙 업데이트 ---------- */
async function runRulesUpdate() {
  const url = document.getElementById('rules-update-url')?.value.trim();
  const type = document.getElementById('rules-update-type')?.value || 'violations';
  if (!url) { showToast('GitHub Raw URL을 입력하세요', 'error'); return; }
  const btn = document.getElementById('btn-rules-update');
  setBtnLoading(btn, true, '업데이트');
  try {
    const data = await api('POST', '/api/validate/rules/update', { github_raw_url: url, rule_type: type });
    showToast(`${data.year}년 규칙 업데이트 완료 (${data.saved})`, 'success');
    validateTabInited = false;
    await loadRulesList();
  } catch (e) {
    showToast(`업데이트 실패: ${e.message}`, 'error');
  } finally {
    setBtnLoading(btn, false, '업데이트');
  }
}

/* =============================================================
   팔레트 (파스텔 색상 테마 10종)
   ============================================================= */
const PALETTES = ['green', 'pink', 'lavender', 'sky', 'peach', 'mint', 'coral', 'lilac', 'butter', 'rose'];

function applyPalette(name) {
  if (!PALETTES.includes(name)) name = 'green';
  if (name === 'green') {
    document.documentElement.removeAttribute('data-palette');
  } else {
    document.documentElement.setAttribute('data-palette', name);
  }
  localStorage.setItem('palette', name);
  $$('.palette-swatch').forEach(btn => {
    btn.classList.toggle('is-active', btn.dataset.palette === name);
  });
}

function setupPalette() {
  const saved = localStorage.getItem('palette') || 'green';
  applyPalette(saved);

  const btn = $('#btn-palette');
  const popup = $('#palette-popup');
  if (!btn || !popup) return;

  btn.addEventListener('click', (e) => {
    e.stopPropagation();
    popup.classList.toggle('is-open');
  });

  document.addEventListener('click', (e) => {
    if (!btn.contains(e.target) && !popup.contains(e.target)) {
      popup.classList.remove('is-open');
    }
  });

  $$('.palette-swatch').forEach(swatch => {
    swatch.addEventListener('click', () => {
      applyPalette(swatch.dataset.palette);
      popup.classList.remove('is-open');
    });
  });
}

/* =============================================================
   부팅
   ============================================================= */
async function boot() {
  document.getElementById('btn-theme-toggle').addEventListener('click', toggleTheme);
  setupPalette();
  bindEvents();
  setupTabRouting();
  setGeminiConnState('off');
  updateDbBadge();
  await refreshDbStatus();
  updateInspectButton();
}

document.addEventListener('DOMContentLoaded', boot);
