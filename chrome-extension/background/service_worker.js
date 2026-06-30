/**
 * Alfaleus Lead Intelligence — Background Service Worker
 * Acts as a relay between content scripts and the popup.
 * Manages session state for extracted lead data.
 */

'use strict';

// ─── Message Relay ────────────────────────────────────────────────────────────

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.type === 'LINKEDIN_DATA' || message.type === 'WEBSITE_DATA') {
    // Persist the most recently extracted data so popup can retrieve it
    // even after content script has already run (chrome.storage.session is
    // cleared on browser restart, which is exactly what we want)
    chrome.storage.session
      .set({ latestExtracted: message.data, extractedAt: Date.now() })
      .then(() => {
        sendResponse({ ok: true });
      })
      .catch((err) => {
        console.warn('[Alfaleus SW] Failed to store extracted data:', err);
        sendResponse({ ok: false, error: err.message });
      });

    // Return true to indicate we'll respond asynchronously
    return true;
  }

  if (message.type === 'GET_EXTRACTED') {
    chrome.storage.session
      .get(['latestExtracted', 'extractedAt'])
      .then(({ latestExtracted, extractedAt }) => {
        sendResponse({ data: latestExtracted || null, extractedAt: extractedAt || null });
      })
      .catch(() => sendResponse({ data: null }));
    return true;
  }

  if (message.type === 'CLEAR_EXTRACTED') {
    chrome.storage.session.remove(['latestExtracted', 'extractedAt']).then(() => {
      sendResponse({ ok: true });
    });
    return true;
  }

  // Handle API proxy to bypass CORS
  if (message.type === 'API_PROXY') {
    fetch(message.url, {
      method: message.method,
      headers: message.headers,
      body: message.body
    })
    .then(async (response) => {
      if (!response.ok) {
        const err = await response.json().catch(() => ({}));
        throw new Error(err.detail || `HTTP ${response.status}`);
      }
      return response.json();
    })
    .then((data) => {
      sendResponse({ success: true, data });
    })
    .catch((error) => {
      sendResponse({ success: false, error: error.message });
    });
    return true;
  }
});

// ─── Extension Install / Update Handler ───────────────────────────────────────

chrome.runtime.onInstalled.addListener(({ reason }) => {
  if (reason === 'install') {
    // Set default API URL on fresh install
    chrome.storage.sync.set({ apiUrl: 'https://alfaleus-backend-production.up.railway.app' });
    console.log('[Alfaleus] Extension installed. Default API URL set to https://alfaleus-backend-production.up.railway.app');
  }
  if (reason === 'update') {
    console.log('[Alfaleus] Extension updated to version', chrome.runtime.getManifest().version);
  }
});

// ─── Tab Update Listener ─────────────────────────────────────────────────────
// When user navigates to a new page, clear stale extracted data

chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
  if (changeInfo.status === 'loading' && changeInfo.url) {
    // New navigation started — clear previous extraction
    chrome.storage.session.remove(['latestExtracted', 'extractedAt']).catch(() => {});
  }
});
