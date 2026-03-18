package com.workflowapp.remote.ui.theme

import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.ReadOnlyComposable
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp

/**
 * Spacing tokens for the Workflow App.
 *
 * Usage:
 *   MaterialTheme.spacing.md   // 16.dp
 *   MaterialTheme.spacing.lg   // 24.dp
 */
data class Spacing(
    val xs:            Dp = 4.dp,
    val sm:            Dp = 8.dp,
    val md:            Dp = 16.dp,
    val lg:            Dp = 24.dp,
    val xl:            Dp = 32.dp,
    val xxl:           Dp = 48.dp,
    /** Standard horizontal screen padding. */
    val screenH:       Dp = 8.dp,
    /** Standard vertical screen padding. */
    val screenV:       Dp = 8.dp,
    /** Minimum interactive touch target. */
    val touchTarget:   Dp = 48.dp,
    /** Card internal padding. */
    val cardPadding:   Dp = 16.dp,
)

val LocalSpacing = staticCompositionLocalOf { Spacing() }

/** Extension for ergonomic access from composables. */
val MaterialTheme.spacing: Spacing
    @Composable
    @ReadOnlyComposable
    get() = LocalSpacing.current
