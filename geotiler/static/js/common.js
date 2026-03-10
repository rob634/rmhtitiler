/**
 * Common JavaScript utilities for geotiler UI
 */

// ============================================================================
// URL Input Helpers
// ============================================================================

/**
 * Set a URL value in an input field
 * @param {string} url - The URL to set
 * @param {string} inputId - The ID of the input element
 */
function setUrl(url, inputId) {
    const input = document.getElementById(inputId);
    if (input) {
        input.value = url;
        input.dispatchEvent(new Event('input', { bubbles: true }));
    }
}


/**
 * Escape HTML special characters
 * @param {string} text - Text to escape
 * @returns {string} Escaped text
 */
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}


// ============================================================================
// Utility Functions
// ============================================================================

/**
 * Debounce function calls
 * @param {Function} func - Function to debounce
 * @param {number} wait - Wait time in milliseconds
 * @returns {Function} Debounced function
 */
function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}


// ============================================================================
// Tab Navigation
// ============================================================================

/**
 * Initialize tab navigation
 * Call this on page load if tabs are present
 */
function initTabs() {
    document.querySelectorAll('.tab-button').forEach(button => {
        button.addEventListener('click', () => {
            const tabGroup = button.closest('.tabs');
            const targetId = button.dataset.tab;

            // Deactivate all tabs in group
            tabGroup.querySelectorAll('.tab-button').forEach(b => b.classList.remove('active'));
            tabGroup.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));

            // Activate clicked tab
            button.classList.add('active');
            const target = document.getElementById(targetId);
            if (target) {
                target.classList.add('active');
            }
        });
    });
}


// ============================================================================
// API Fetch Helper
// ============================================================================

/**
 * Fetch JSON from an API endpoint with error handling.
 * Returns a result object — never throws.
 * @param {string} url - URL to fetch
 * @param {object} [options] - Fetch options (method, body, timeout)
 * @returns {Promise<{ok: boolean, data?: any, error?: string}>}
 */
async function fetchJSON(url, options = {}) {
    const { method = 'GET', body = null, timeout = 30000 } = options;
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeout);

    try {
        const fetchOptions = {
            method,
            signal: controller.signal,
            headers: { 'Content-Type': 'application/json' },
        };
        if (body) fetchOptions.body = JSON.stringify(body);

        const response = await fetch(url, fetchOptions);
        const data = await response.json();

        if (!response.ok) {
            return { ok: false, error: data.detail || `HTTP ${response.status}` };
        }
        return { ok: true, data };
    } catch (err) {
        if (err.name === 'AbortError') return { ok: false, error: 'Request timed out' };
        return { ok: false, error: err.message };
    } finally {
        clearTimeout(timer);
    }
}


// ============================================================================
// URL Parameter Helpers
// ============================================================================

/**
 * Get a query parameter value from the current URL
 * @param {string} name - Parameter name
 * @returns {string|null} Parameter value or null
 */
function getQueryParam(name) {
    return new URLSearchParams(window.location.search).get(name);
}

/**
 * Set or remove a query parameter in the current URL (no page reload)
 * @param {string} name - Parameter name
 * @param {string|null} value - Value to set, or null/undefined/'' to remove
 */
function setQueryParam(name, value) {
    const url = new URL(window.location);
    if (value === null || value === undefined || value === '') {
        url.searchParams.delete(name);
    } else {
        url.searchParams.set(name, value);
    }
    window.history.replaceState({}, '', url);
}


// ============================================================================
// Viewer URL Builder
// ============================================================================

/**
 * Build a URL to one of the map viewer pages
 * @param {string} type - Viewer type (e.g., 'raster', 'vector', 'zarr')
 * @param {object} params - Query parameters
 * @returns {string} Full viewer URL with query string
 */
function buildViewerUrl(type, params) {
    const base = '/viewer/' + type;
    const qs = new URLSearchParams(params).toString();
    return qs ? base + '?' + qs : base;
}


// ============================================================================
// Toast Notifications
// ============================================================================

/**
 * Show a toast notification message.
 * Gracefully degrades if toast-container is not present.
 * @param {string} message - Message text
 * @param {string} [type='info'] - Notification type ('info', 'success', 'warning', 'error')
 */
function showNotification(message, type = 'info') {
    const container = document.getElementById('toast-container');
    if (!container) return;

    const toast = document.createElement('div');
    toast.className = 'toast toast-' + type;
    toast.textContent = message;
    container.appendChild(toast);

    // Auto-remove after 4 seconds
    setTimeout(() => {
        toast.style.opacity = '0';
        setTimeout(() => toast.remove(), 300);
    }, 4000);
}


// ============================================================================
// Auto-initialization
// ============================================================================

document.addEventListener('DOMContentLoaded', () => {
    // Initialize tabs if present
    if (document.querySelector('.tabs')) {
        initTabs();
    }
});
