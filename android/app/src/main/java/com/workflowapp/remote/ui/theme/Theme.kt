package com.workflowapp.remote.ui.theme

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Shapes
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.ui.unit.dp

// ── CompositionLocal for extras not in M3 ColorScheme ─────────────────────
val LocalCustomColors = staticCompositionLocalOf { CustomColors() }

/** Extension property for ergonomic access from composables. */
val MaterialTheme.customColors: CustomColors
    @Composable get() = LocalCustomColors.current

// ── Dark colour scheme — Graphite Amber D19 ───────────────────────────────
private val WorkflowDarkColorScheme = darkColorScheme(
    primary         = AppColors.PrimaryAmber,
    onPrimary       = AppColors.OnPrimary,
    secondary       = AppColors.PrimaryAmber,
    onSecondary     = AppColors.OnPrimary,
    tertiary        = AppColors.ElevatedSurface,
    onTertiary      = AppColors.OnSurface,
    background      = AppColors.Background,
    onBackground    = AppColors.OnSurface,
    surface         = AppColors.Surface,
    onSurface       = AppColors.OnSurface,
    surfaceVariant  = AppColors.ElevatedSurface,
    onSurfaceVariant = AppColors.SecondaryText,
    outline         = AppColors.MutedText,
    outlineVariant  = AppColors.ElevatedSurface,
)

// ── Shapes ─────────────────────────────────────────────────────────────────
private val WorkflowShapes = Shapes(
    small      = RoundedCornerShape(4.dp),
    medium     = RoundedCornerShape(8.dp),
    large      = RoundedCornerShape(12.dp),
    extraLarge = RoundedCornerShape(16.dp),
)

// ── Theme entry point ──────────────────────────────────────────────────────
@Composable
fun WorkflowAppTheme(
    content: @Composable () -> Unit,
) {
    CompositionLocalProvider(
        LocalCustomColors provides CustomColors(),
        LocalSpacing      provides Spacing(),
    ) {
        MaterialTheme(
            colorScheme = WorkflowDarkColorScheme,
            typography  = WorkflowTypography,
            shapes      = WorkflowShapes,
            content     = content,
        )
    }
}
