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
 * Get the trimmed value from an input field
 * @param {string} inputId - The ID of the input element
 * @returns {string} The trimmed value or empty string
 */
function getInputValue(inputId) {
    const input = document.getElementById(inputId);
    return input ? input.value.trim() : '';
}


// ============================================================================
// API Helpers
// ============================================================================

/**
 * Fetch info for a COG URL
 * @param {string} url - The COG URL to query
 * @param {string} resultContainerId - ID of element to display results
 */
async function getCogInfo(url, resultContainerId) {
    if (!url) {
        showError(resultContainerId, 'Please enter a URL');
        return;
    }

    const container = document.getElementById(resultContainerId);
    if (container) {
        container.innerHTML = '<p class="loading">Loading...</p>';
    }

    try {
        const response = await fetch(`/cog/info?url=${encodeURIComponent(url)}`);
        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.detail || 'Failed to fetch info');
        }

        displayJson(resultContainerId, data);
    } catch (error) {
        showError(resultContainerId, error.message);
    }
}

/**
 * Fetch info for a Zarr/XArray URL
 * @param {string} url - The Zarr URL to query
 * @param {string} resultContainerId - ID of element to display results
 */
async function getXarrayInfo(url, resultContainerId) {
    if (!url) {
        showError(resultContainerId, 'Please enter a URL');
        return;
    }

    const container = document.getElementById(resultContainerId);
    if (container) {
        container.innerHTML = '<p class="loading">Loading...</p>';
    }

    try {
        const response = await fetch(`/xarray/info?url=${encodeURIComponent(url)}`);
        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.detail || 'Failed to fetch info');
        }

        displayJson(resultContainerId, data);
    } catch (error) {
        showError(resultContainerId, error.message);
    }
}

/**
 * Open tile viewer in new tab
 * @param {string} baseUrl - Base URL path (e.g., '/cog')
 * @param {string} url - The data URL
 */
function viewTiles(baseUrl, url) {
    if (!url) {
        alert('Please enter a URL first');
        return;
    }
    window.open(`${baseUrl}/viewer?url=${encodeURIComponent(url)}`, '_blank');
}


// ============================================================================
// Display Helpers
// ============================================================================

/**
 * Display JSON data in a container with formatting
 * @param {string} containerId - The container element ID
 * @param {object} data - The data to display
 */
function displayJson(containerId, data) {
    const container = document.getElementById(containerId);
    if (container) {
        container.innerHTML = `<pre>${formatJson(data)}</pre>`;
    }
}

/**
 * Show an error message in a container
 * @param {string} containerId - The container element ID
 * @param {string} message - The error message
 */
function showError(containerId, message) {
    const container = document.getElementById(containerId);
    if (container) {
        container.innerHTML = `<div class="callout callout-warning"><strong>Error:</strong> ${escapeHtml(message)}</div>`;
    }
}

/**
 * Show a success message in a container
 * @param {string} containerId - The container element ID
 * @param {string} message - The success message
 */
function showSuccess(containerId, message) {
    const container = document.getElementById(containerId);
    if (container) {
        container.innerHTML = `<div class="callout callout-success">${escapeHtml(message)}</div>`;
    }
}

/**
 * Format JSON with syntax highlighting
 * @param {object} data - The data to format
 * @returns {string} Formatted HTML string
 */
function formatJson(data) {
    const json = JSON.stringify(data, null, 2);
    return escapeHtml(json);
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
// Clipboard Helpers
// ============================================================================

/**
 * Copy text to clipboard with visual feedback
 * @param {string} text - Text to copy
 * @param {HTMLElement} [button] - Optional button element for feedback
 */
async function copyToClipboard(text, button) {
    try {
        await navigator.clipboard.writeText(text);

        if (button) {
            const originalText = button.textContent;
            button.textContent = 'Copied!';
            button.classList.add('btn-success');

            setTimeout(() => {
                button.textContent = originalText;
                button.classList.remove('btn-success');
            }, 2000);
        }
    } catch (error) {
        console.error('Failed to copy to clipboard:', error);
        // Fallback for older browsers
        const textarea = document.createElement('textarea');
        textarea.value = text;
        textarea.style.position = 'fixed';
        textarea.style.opacity = '0';
        document.body.appendChild(textarea);
        textarea.select();
        document.execCommand('copy');
        document.body.removeChild(textarea);
    }
}

/**
 * Copy content from an element to clipboard
 * @param {string} elementId - ID of element containing text to copy
 * @param {HTMLElement} [button] - Optional button for feedback
 */
function copyElementContent(elementId, button) {
    const element = document.getElementById(elementId);
    if (element) {
        copyToClipboard(element.textContent, button);
    }
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

/**
 * Throttle function calls
 * @param {Function} func - Function to throttle
 * @param {number} limit - Minimum time between calls in milliseconds
 * @returns {Function} Throttled function
 */
function throttle(func, limit) {
    let inThrottle;
    return function executedFunction(...args) {
        if (!inThrottle) {
            func(...args);
            inThrottle = true;
            setTimeout(() => inThrottle = false, limit);
        }
    };
}

/**
 * Format bytes to human readable string
 * @param {number} bytes - Number of bytes
 * @param {number} [decimals=2] - Decimal places
 * @returns {string} Formatted string
 */
function formatBytes(bytes, decimals = 2) {
    if (bytes === 0) return '0 Bytes';

    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));

    return parseFloat((bytes / Math.pow(k, i)).toFixed(decimals)) + ' ' + sizes[i];
}

/**
 * Format a date string to locale format
 * @param {string} dateString - ISO date string
 * @returns {string} Formatted date
 */
function formatDate(dateString) {
    try {
        return new Date(dateString).toLocaleString();
    } catch {
        return dateString;
    }
}


// ============================================================================
// Form Helpers
// ============================================================================

/**
 * Serialize form data to object
 * @param {HTMLFormElement} form - Form element
 * @returns {object} Form data as object
 */
function serializeForm(form) {
    const formData = new FormData(form);
    const data = {};
    for (const [key, value] of formData.entries()) {
        data[key] = value;
    }
    return data;
}

/**
 * Populate form fields from object
 * @param {HTMLFormElement} form - Form element
 * @param {object} data - Data to populate
 */
function populateForm(form, data) {
    for (const [key, value] of Object.entries(data)) {
        const field = form.elements[key];
        if (field) {
            field.value = value;
        }
    }
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
// Auto-initialization
// ============================================================================

document.addEventListener('DOMContentLoaded', () => {
    // Initialize tabs if present
    if (document.querySelector('.tabs')) {
        initTabs();
    }
});
