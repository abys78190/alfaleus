/**
 * Alfaleus Lead Intelligence — LinkedIn Content Script
 * Extracts profile and company data from LinkedIn pages.
 * Handles LinkedIn's React SPA navigation via MutationObserver.
 */

(function () {
  'use strict';

  // ─── Page type detection ───────────────────────────────────────────────────
  const isProfile = () => location.pathname.startsWith('/in/');
  const isCompany = () => location.pathname.startsWith('/company/');

  // ─── DOM Utilities ─────────────────────────────────────────────────────────

  /**
   * Wait for a CSS selector to appear in the DOM.
   * Uses MutationObserver with a fallback timeout.
   */
  function waitForElement(selector, timeout = 10000) {
    return new Promise((resolve) => {
      const existing = document.querySelector(selector);
      if (existing) return resolve(existing);

      const timer = setTimeout(() => {
        observer.disconnect();
        resolve(null); // timed out — return null gracefully
      }, timeout);

      const observer = new MutationObserver(() => {
        const el = document.querySelector(selector);
        if (el) {
          clearTimeout(timer);
          observer.disconnect();
          resolve(el);
        }
      });

      observer.observe(document.body || document.documentElement, {
        subtree: true,
        childList: true,
      });
    });
  }

  /** Safe text helper — returns trimmed text or empty string */
  function getText(el) {
    if (!el) return '';
    return (el.innerText || el.textContent || '').trim();
  }

  /** Safe attribute helper */
  function getAttr(selector, attr) {
    const el = document.querySelector(selector);
    return el ? (el.getAttribute(attr) || '').trim() : '';
  }

  // ─── Profile Extraction ────────────────────────────────────────────────────

  async function extractProfileData() {
    // Wait for the main profile container
    await waitForElement('.pv-top-card', 8000);

    // Small extra delay to let React finish hydrating dynamic sub-sections
    await new Promise((r) => setTimeout(r, 1200));

    // ── Name ──────────────────────────────────────────────────────────────────
    let name = '';
    const nameSelectors = [
      'h1.text-heading-xlarge',
      'h1[class*="text-heading-xlarge"]',
      '.pv-top-card--list h1',
      '.artdeco-entity-lockup__title h1',
      'h1',
    ];
    for (const sel of nameSelectors) {
      const el = document.querySelector(sel);
      if (el && getText(el).length > 1) {
        name = getText(el);
        break;
      }
    }
    // Fallback: og:title or document.title
    if (!name) {
      const ogTitle = getAttr("meta[property='og:title']", 'content') || document.title;
      if (ogTitle) {
        name = ogTitle.split('|')[0].split('-')[0].trim();
      }
    }

    // ── Title / Headline ──────────────────────────────────────────────────────
    let title = '';
    const titleSelectors = [
      '.text-body-medium.break-words',
      '[data-generated-suggestion-target] .text-body-medium',
      '.pv-top-card .text-body-medium',
      '.ph5 .text-body-medium',
      'div.text-body-medium',
    ];
    for (const sel of titleSelectors) {
      const el = document.querySelector(sel);
      const text = getText(el);
      if (text && text.length > 2 && !text.includes('Connect') && !text.includes('Follow')) {
        title = text;
        break;
      }
    }
    // Try og:description or document.title as a fallback
    if (!title) {
      const ogDesc = getAttr("meta[property='og:description']", 'content');
      if (ogDesc) title = ogDesc.split(' at ')[0].split('...')[0].trim();
    }

    // ── Company ───────────────────────────────────────────────────────────────
    let company = '';
    // Strategy 1: "at CompanyName" in the headline/title
    if (title && title.toLowerCase().includes(' at ')) {
      company = title.split(/ at /i).pop().trim();
    }
    // Strategy 2: Right panel current company badge
    if (!company) {
      const companySelectors = [
        'button[aria-label*="Current company"]',
        'a[aria-label*="Current company"]',
        '.pv-text-details__right-panel .pv-text-details__right-panel-item',
        '.pv-top-card--experience-list-item span',
        '.pv-top-card--experience-list-item a'
      ];
      for (const sel of companySelectors) {
        const el = document.querySelector(sel);
        const text = getText(el);
        if (text && text.length > 1) {
          company = text;
          break;
        }
      }
    }
    // Strategy 3: current position in experience section
    if (!company) {
      const expSelectors = [
        '#experience ~ div .t-bold span[aria-hidden="true"]',
        'section[id*="experience"] .t-bold span[aria-hidden="true"]',
        '.pvs-entity .t-bold span[aria-hidden="true"]',
      ];
      for (const sel of expSelectors) {
        const els = document.querySelectorAll(sel);
        for (const el of els) {
          const text = getText(el);
          if (text && text.length > 1) {
            company = text;
            break;
          }
        }
        if (company) break;
      }
    }

    // ── Location ──────────────────────────────────────────────────────────────
    let location_text = '';
    const locSelectors = [
      '.text-body-small.inline.t-black--light',
      '.pv-top-card--list-bullet span:first-child',
      'span.text-body-small[class*="t-black--light"]',
    ];
    for (const sel of locSelectors) {
      const el = document.querySelector(sel);
      const text = getText(el);
      if (text && text.length > 1) {
        location_text = text;
        break;
      }
    }

    // ── LinkedIn URL ──────────────────────────────────────────────────────────
    const linkedin_url = window.location.href.split('?')[0];

    return {
      name,
      title,
      company,
      location: location_text,
      linkedin_url,
      url: linkedin_url,
      page_type: 'profile',
      source: 'linkedin',
    };
  }

  // ─── Company Page Extraction ───────────────────────────────────────────────

  async function extractCompanyData() {
    await waitForElement('.org-top-card', 8000);
    await new Promise((r) => setTimeout(r, 1000));

    // ── Company Name ──────────────────────────────────────────────────────────
    let name = '';
    const nameSelectors = [
      'h1.org-top-card-summary__title',
      '.org-top-card h1',
      'h1[class*="org-top-card"]',
      '.artdeco-entity-lockup__title h1',
      'h1',
    ];
    for (const sel of nameSelectors) {
      const el = document.querySelector(sel);
      if (el && getText(el).length > 1) {
        name = getText(el);
        break;
      }
    }
    if (!name) name = getAttr("meta[property='og:title']", 'content').split('|')[0].trim();

    // ── Tagline ───────────────────────────────────────────────────────────────
    let tagline = '';
    const taglineSelectors = [
      '.org-top-card-summary__tagline',
      '.org-top-card p',
      '.org-page-details__definition-text',
    ];
    for (const sel of taglineSelectors) {
      const el = document.querySelector(sel);
      if (el && getText(el).length > 2) {
        tagline = getText(el);
        break;
      }
    }

    // ── Industry / Size ───────────────────────────────────────────────────────
    let industry = '';
    let size = '';
    const definitionItems = document.querySelectorAll(
      '.org-page-details__definition-list dt, .org-page-details__definition-list dd'
    );
    let lastDt = '';
    definitionItems.forEach((el) => {
      if (el.tagName === 'DT') {
        lastDt = getText(el).toLowerCase();
      } else if (el.tagName === 'DD') {
        if (lastDt.includes('industry')) industry = getText(el);
        if (lastDt.includes('size') || lastDt.includes('employees')) size = getText(el);
      }
    });

    // Fallback: look for the info list items
    if (!industry || !size) {
      const infoEls = document.querySelectorAll(
        '.org-top-card-summary-info-list__info-item, .org-top-card-summary__info-item'
      );
      infoEls.forEach((el) => {
        const text = getText(el);
        if (!industry && text && !text.match(/^\d/)) industry = text;
        if (!size && text && text.match(/\d+/)) size = text;
      });
    }

    const linkedin_url = window.location.href.split('?')[0];

    return {
      name,
      company: name,
      tagline,
      industry,
      company_size: size,
      linkedin_url,
      url: linkedin_url,
      page_type: 'company',
      source: 'linkedin',
    };
  }

  // ─── Main Extraction Orchestrator ─────────────────────────────────────────

  async function extract() {
    let data = {};

    try {
      if (isProfile()) {
        data = await extractProfileData();
      } else if (isCompany()) {
        data = await extractCompanyData();
      } else {
        return; // Not a relevant LinkedIn page
      }

      // Persist in sessionStorage so popup can read via scripting.executeScript
      try {
        sessionStorage.setItem('alfaleus_extracted', JSON.stringify(data));
      } catch (e) {
        // Quota exceeded or private mode — ignore
      }

      // Send to background / popup via runtime message
      chrome.runtime.sendMessage({ type: 'LINKEDIN_DATA', data }, () => {
        // Suppress "no receiving end" errors gracefully
        if (chrome.runtime.lastError) { /* noop */ }
      });
    } catch (err) {
      console.warn('[Alfaleus] Extraction error:', err);
    }
  }

  // ─── SPA Navigation Detection (MutationObserver) ──────────────────────────

  let lastUrl = location.href;
  let extractTimeout = null;

  const navObserver = new MutationObserver(() => {
    if (location.href !== lastUrl) {
      lastUrl = location.href;
      // Debounce: wait for React to render the new page
      clearTimeout(extractTimeout);
      extractTimeout = setTimeout(extract, 2200);
    }
  });

  navObserver.observe(document.documentElement, {
    subtree: true,
    childList: true,
  });

  // Initial extraction on page load
  extract();
})();
