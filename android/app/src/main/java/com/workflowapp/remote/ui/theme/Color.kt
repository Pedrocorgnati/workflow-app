package com.workflowapp.remote.ui.theme

import androidx.compose.ui.graphics.Color

// ── Base colour palette — Graphite Amber D19 (Dark only) ──────────────────
object AppColors {
    val Background      = Color(0xFF1C1917)  // Main screen background
    val Surface         = Color(0xFF292524)  // Cards, containers
    val ElevatedSurface = Color(0xFF44403C)  // InteractionCard, active items
    val PrimaryAmber    = Color(0xFFD4A574)  // Primary action colour (amber)
    val OnPrimary       = Color(0xFF1C1917)  // Text/icon over PrimaryAmber
    val OnSurface       = Color(0xFFFAFAF9)  // Primary text on dark surfaces
    val SecondaryText   = Color(0xFFA8A29E)  // Secondary labels, metadata
    val MutedText       = Color(0xFF78716C)  // Placeholders, disabled hints

    // ── Semantic ──────────────────────────────────────────────────────────
    val Success = Color(0xFF34D399)  // Connected, completed
    val Warning = Color(0xFFFBBF24)  // Reconnecting, truncation notice
    val Info    = Color(0xFF38BDF8)  // Connecting, informational
    // Error: use MaterialTheme.colorScheme.error (Material3 default ~#EF4444)
}

// ── Custom CompositionLocal extras (not in M3 ColorScheme) ─────────────────
data class CustomColors(
    val success: Color  = AppColors.Success,
    val warning: Color  = AppColors.Warning,
    val info:    Color  = AppColors.Info,
    val elevated: Color = AppColors.ElevatedSurface,
)
