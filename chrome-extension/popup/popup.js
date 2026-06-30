/**
 * Alfaleus Lead Intelligence — Popup Script
 * Handles UI logic for the Chrome extension popup.
 */

'use strict';

const API_BASE_DEFAULT = 'https://alfaleus-backend-production.up.railway.app';

// ─── State ────────────────────────────────────────────────────────────────────
let apiUrl = API_BASE_DEFAULT;
let extractedData = null;
let currentTab = null;

// ─── Utility ──────────────────────────────────────────────────────────────────
const $ = (id) => document.getElementById(id);
const show = (el) => { if (el) el.style.display = ''; };
const hide = (el) => { if (el) el.style.display = 'none'; };

function setStatus(msg, type = 'info') {
  const el = $('status-message');
  if (!el) return;
  el.textContent = msg;
  el.className = `status-message status-${type}`;
  el.style.display = msg ? '' : 'none';
}

function setLoading(loading) {
  const btn = $('enrich-btn');
  if (!btn) return;
  btn.disabled = loading;
  btn.textContent = loading ? '⏳ Enriching...' : '⚡ Enrich This Lead';
}

// ─── Init ─────────────────────────────────────────────────────────────────────
async function init() {
  // Load saved API URL
  const stored = await chrome.storage.sync.get(['apiUrl']);
  apiUrl = stored.apiUrl || API_BASE_DEFAULT;
  const urlInput = $('api-url-input');
  if (urlInput) urlInput.value = apiUrl;

  // Get current tab
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  currentTab = tab;

  // Detect page type
  detectPageType(tab);

  // Try to get previously extracted data
  await loadExtractedData();

  // Set up event listeners
  setupEventListeners();
}

function detectPageType(tab) {
  const url = tab?.url || '';
  const pageTypeBar = $('page-type-bar');
  const pageIcon = $('page-type-icon');
  const pageLabel = $('page-type-label');

  if (url.includes('linkedin.com/in/')) {
    if (pageIcon) pageIcon.textContent = '👤';
    if (pageLabel) pageLabel.textContent = 'LinkedIn Profile';
  } else if (url.includes('linkedin.com/company/')) {
    if (pageIcon) pageIcon.textContent = '🏢';
    if (pageLabel) pageLabel.textContent = 'LinkedIn Company';
  } else {
    if (pageIcon) pageIcon.textContent = '🌐';
    if (pageLabel) pageLabel.textContent = 'Company Website';
  }
}

async function loadExtractedData() {
  // First try sessionStorage via scripting API
  if (currentTab?.id) {
    try {
      const results = await chrome.scripting.executeScript({
        target: { tabId: currentTab.id },
        func: () => {
          try {
            const raw = sessionStorage.getItem('alfaleus_extracted');
            return raw ? JSON.parse(raw) : null;
          } catch (_) { return null; }
        },
      });
      if (results?.[0]?.result) {
        extractedData = results[0].result;
        populateForm(extractedData);
        return;
      }
    } catch (_) {}
  }

  // Fallback to background storage
  const { data } = await chrome.runtime.sendMessage({ type: 'GET_EXTRACTED' });
  if (data) {
    extractedData = data;
    populateForm(extractedData);
  }
}

function populateForm(data) {
  if (!data) return;
  const fields = {
    'field-name': data.name || '',
    'field-title': data.title || '',
    'field-company': data.company || '',
    'field-email': data.email || '',
    'field-url': data.url || data.linkedin_url || '',
    'field-linkedin': data.linkedin_url || '',
  };
  Object.entries(fields).forEach(([id, val]) => {
    const el = $(id);
    if (el) el.value = val;
  });

  if (data.name || data.company) {
    setStatus('✓ Lead data extracted automatically', 'success');
  }
}

// ─── Event Listeners ─────────────────────────────────────────────────────────
function setupEventListeners() {
  // Settings toggle
  const settingsToggle = $('settings-toggle');
  const settingsPanel = $('settings-panel');
  if (settingsToggle && settingsPanel) {
    settingsToggle.addEventListener('click', () => {
      const visible = settingsPanel.style.display !== 'none';
      settingsPanel.style.display = visible ? 'none' : '';
    });
  }

  // Save settings
  const saveSettings = $('save-settings');
  if (saveSettings) {
    saveSettings.addEventListener('click', async () => {
      const urlInput = $('api-url-input');
      if (urlInput) {
        apiUrl = urlInput.value.trim().replace(/\/$/, '');
        await chrome.storage.sync.set({ apiUrl });
        setStatus('Settings saved', 'success');
      }
    });
  }

  // Extract button (manual re-extraction)
  const extractBtn = $('extract-btn');
  if (extractBtn) {
    extractBtn.addEventListener('click', async () => {
      if (!currentTab?.id) return;
      extractBtn.disabled = true;
      extractBtn.textContent = '🔄 Extracting...';
      try {
        await chrome.scripting.executeScript({
          target: { tabId: currentTab.id },
          files: [
            currentTab.url?.includes('linkedin.com') ? '/content/linkedin.js' : '/content/website.js',
          ],
        });
        await new Promise(r => setTimeout(r, 2500));
        await loadExtractedData();
      } catch (e) {
        setStatus('Could not extract — try refreshing the page', 'error');
      } finally {
        extractBtn.disabled = false;
        extractBtn.textContent = '🔍 Re-Extract';
      }
    });
  }

  // Enrich button
  const enrichBtn = $('enrich-btn');
  if (enrichBtn) {
    enrichBtn.addEventListener('click', enrichLead);
  }

  // Open dashboard
  const openDashboard = () => {
    chrome.tabs.create({ url: 'https://frontend-psi-teal-lcd2aq9ol8.vercel.app' });
  };
  
  const dashboardBtn = $('open-app');
  if (dashboardBtn) dashboardBtn.addEventListener('click', openDashboard);
  
  const footerDashboardBtn = $('footer-open-app');
  if (footerDashboardBtn) footerDashboardBtn.addEventListener('click', (e) => {
    e.preventDefault();
    openDashboard();
  });

  // View in dashboard (after successful enrich)
  const viewBtn = $('view-in-dashboard');
  if (viewBtn) {
    viewBtn.addEventListener('click', () => {
      const leadId = viewBtn.dataset.leadId;
      if (leadId) {
        chrome.tabs.create({ url: `https://frontend-psi-teal-lcd2aq9ol8.vercel.app/leads/${leadId}` });
      }
    });
  }
}

// ─── Enrich Lead ─────────────────────────────────────────────────────────────
async function enrichLead() {
  const payload = {
    name: $('field-name')?.value.trim() || null,
    title: $('field-title')?.value.trim() || null,
    company: $('field-company')?.value.trim() || null,
    email: $('field-email')?.value.trim() || null,
    url: $('field-url')?.value.trim() || currentTab?.url || null,
    linkedin_url: $('field-linkedin')?.value.trim() || null,
  };

  if (!payload.name && !payload.company && !payload.email) {
    setStatus('Please fill in at least a name or company', 'error');
    return;
  }

  setLoading(true);
  setStatus('Sending to enrichment pipeline...', 'info');

  try {
    const response = await new Promise((resolve, reject) => {
      chrome.runtime.sendMessage({
        type: 'API_PROXY',
        url: `${apiUrl}/api/v1/leads/extension`,
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      }, (res) => {
        if (chrome.runtime.lastError) {
          reject(new Error(chrome.runtime.lastError.message));
        } else if (!res || !res.success) {
          reject(new Error((res && res.error) || 'Failed to fetch'));
        } else {
          resolve(res.data);
        }
      });
    });

    const result = response;

    // Show success state
    const successEl = $('success-state');
    const formEl = $('lead-form');
    if (successEl) show(successEl);
    if (formEl) hide(formEl);

    setStatus('✅ Lead queued for enrichment!', 'success');

    // Wire up "View in Dashboard" button
    const viewBtn = $('view-in-dashboard');
    if (viewBtn && result.id) {
      viewBtn.dataset.leadId = result.id;
    }

    // Clear extracted data from storage
    chrome.runtime.sendMessage({ type: 'CLEAR_EXTRACTED' });

  } catch (e) {
    setStatus(`❌ Error: ${e.message}`, 'error');
    console.error('[Alfaleus] Enrich failed:', e);
  } finally {
    setLoading(false);
  }
}

// ─── Boot ─────────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', init);
