"""
Design System Theme for NiceGUI Dashboard.

Consistent styling across the geospatial platform dashboard.
"""

from nicegui import ui

# =============================================================================
# DESIGN SYSTEM COLORS
# =============================================================================

COLORS = {
    # Primary palette
    "blue_primary": "#0071BC",
    "blue_dark": "#245AAD",
    "navy": "#053657",
    "cyan": "#00A3DA",
    "gold": "#FFC14D",

    # Neutral palette
    "gray": "#626F86",
    "gray_light": "#e9ecef",
    "bg": "#f8f9fa",
    "white": "#ffffff",

    # Status colors
    "status_queued_bg": "#f3f4f6",
    "status_queued_fg": "#6b7280",
    "status_pending_bg": "#fef3c7",
    "status_pending_fg": "#d97706",
    "status_processing_bg": "#dbeafe",
    "status_processing_fg": "#0071BC",
    "status_completed_bg": "#d1fae5",
    "status_completed_fg": "#059669",
    "status_failed_bg": "#fee2e2",
    "status_failed_fg": "#dc2626",

    # Health status
    "healthy": "#10b981",
    "warning": "#f59e0b",
    "unhealthy": "#ef4444",
    "unknown": "#6b7280",
}

# =============================================================================
# TYPOGRAPHY
# =============================================================================

FONTS = {
    "family": "'Open Sans', Arial, sans-serif",
    "mono": "'Monaco', 'Courier New', monospace",
}

# =============================================================================
# CUSTOM CSS
# =============================================================================

CUSTOM_CSS = """
/* Import Open Sans font */
@import url('https://fonts.googleapis.com/css2?family=Open+Sans:wght@400;600;700&display=swap');

/* CSS Variables */
:root {
    --ds-blue-primary: #0071BC;
    --ds-blue-dark: #245AAD;
    --ds-navy: #053657;
    --ds-cyan: #00A3DA;
    --ds-gold: #FFC14D;
    --ds-gray: #626F86;
    --ds-gray-light: #e9ecef;
    --ds-bg: #f8f9fa;
}

/* Global font */
body, .q-page, .nicegui-content {
    font-family: 'Open Sans', Arial, sans-serif !important;
    background: var(--ds-bg) !important;
}

/* Header styling */
.q-header {
    background: var(--ds-navy) !important;
}

/* Card styling */
.q-card {
    border-radius: 3px !important;
    box-shadow: 0 1px 3px rgba(0,0,0,0.1) !important;
}

/* Table styling */
.q-table {
    border-radius: 8px !important;
    overflow: hidden;
}

.q-table thead {
    background: #f9fafb;
}

.q-table th {
    font-weight: 600 !important;
    color: #374151 !important;
    text-transform: uppercase;
    font-size: 0.75rem !important;
}

/* Status badge styling */
.q-badge {
    font-weight: 600 !important;
    text-transform: uppercase;
    font-size: 0.65rem !important;
    padding: 4px 8px !important;
}

/* Monospace text */
.mono, .font-mono {
    font-family: 'Monaco', 'Courier New', monospace !important;
}

/* Page title styling */
.page-title {
    font-size: 24px;
    font-weight: 700;
    color: var(--ds-navy);
}

/* Status indicator animations */
@keyframes pulse-healthy {
    0%, 100% { box-shadow: 0 0 0 0 rgba(16, 185, 129, 0.4); }
    50% { box-shadow: 0 0 0 4px rgba(16, 185, 129, 0); }
}

@keyframes pulse-unhealthy {
    0%, 100% { box-shadow: 0 0 0 0 rgba(239, 68, 68, 0.4); }
    50% { box-shadow: 0 0 0 4px rgba(239, 68, 68, 0); }
}

.status-pulse-healthy {
    animation: pulse-healthy 2s ease-in-out infinite;
}

.status-pulse-unhealthy {
    animation: pulse-unhealthy 1.5s ease-in-out infinite;
}
"""


def apply_theme():
    """Apply the design system theme to a NiceGUI page."""
    # Add Open Sans font
    ui.add_head_html('''
        <link rel="preconnect" href="https://fonts.googleapis.com">
        <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
        <link href="https://fonts.googleapis.com/css2?family=Open+Sans:wght@400;600;700&display=swap" rel="stylesheet">
    ''')

    # Add custom CSS
    ui.add_head_html(f'<style>{CUSTOM_CSS}</style>')


# =============================================================================
# STATUS HELPERS
# =============================================================================

def status_badge(status: str) -> ui.badge:
    """Create a styled status badge."""
    status_lower = status.lower()

    colors = {
        "queued": {"bg": COLORS["status_queued_bg"], "fg": COLORS["status_queued_fg"]},
        "pending": {"bg": COLORS["status_pending_bg"], "fg": COLORS["status_pending_fg"]},
        "processing": {"bg": COLORS["status_processing_bg"], "fg": COLORS["status_processing_fg"]},
        "completed": {"bg": COLORS["status_completed_bg"], "fg": COLORS["status_completed_fg"]},
        "failed": {"bg": COLORS["status_failed_bg"], "fg": COLORS["status_failed_fg"]},
        "healthy": {"bg": "#d1fae5", "fg": "#059669"},
        "unhealthy": {"bg": "#fee2e2", "fg": "#dc2626"},
        "warning": {"bg": "#fef3c7", "fg": "#d97706"},
        "degraded": {"bg": "#fef3c7", "fg": "#d97706"},
    }

    style = colors.get(status_lower, {"bg": COLORS["gray_light"], "fg": COLORS["gray"]})

    badge = ui.badge(status.upper())
    badge.style(f"background-color: {style['bg']}; color: {style['fg']};")
    return badge


def health_indicator(status: str, size: str = "md") -> ui.icon:
    """Create a health status indicator icon."""
    status_lower = status.lower()

    icons = {
        "healthy": ("check_circle", COLORS["healthy"]),
        "warning": ("warning", COLORS["warning"]),
        "degraded": ("warning", COLORS["warning"]),
        "unhealthy": ("error", COLORS["unhealthy"]),
        "unknown": ("help", COLORS["unknown"]),
        "disabled": ("block", COLORS["gray"]),
    }

    icon_name, color = icons.get(status_lower, ("help", COLORS["gray"]))
    return ui.icon(icon_name, color=color, size=size)


def status_dot(status: str) -> ui.element:
    """Create a small status dot indicator."""
    status_lower = status.lower()

    colors = {
        "healthy": COLORS["healthy"],
        "warning": COLORS["warning"],
        "degraded": COLORS["warning"],
        "unhealthy": COLORS["unhealthy"],
        "unknown": COLORS["unknown"],
        "disabled": COLORS["gray"],
    }

    color = colors.get(status_lower, COLORS["unknown"])
    pulse_class = "status-pulse-healthy" if status_lower == "healthy" else ""
    if status_lower == "unhealthy":
        pulse_class = "status-pulse-unhealthy"

    return ui.element("span").classes(pulse_class).style(
        f"display: inline-block; width: 12px; height: 12px; border-radius: 50%; "
        f"background: {color}; border: 2px solid white; box-shadow: 0 1px 3px rgba(0,0,0,0.2);"
    )
