package com.workflowapp.remote.ui.theme

import androidx.compose.material3.Typography
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.sp

// Monospace family for output area (JetBrains Mono maps to system monospace in release)
val MonospaceFamily: FontFamily = FontFamily.Monospace

// Workflow App typography — Graphite Amber D19 scale (mobile-adjusted sp values)
val WorkflowTypography = Typography(
    bodySmall = TextStyle(
        fontFamily  = FontFamily.Default,
        fontSize    = 11.sp,
        lineHeight  = 16.sp,
        fontWeight  = FontWeight.Normal,
    ),
    bodyMedium = TextStyle(
        fontFamily  = FontFamily.Default,
        fontSize    = 13.sp,
        lineHeight  = 20.sp,
        fontWeight  = FontWeight.Normal,
    ),
    bodyLarge = TextStyle(
        fontFamily  = FontFamily.Default,
        fontSize    = 14.sp,
        lineHeight  = 20.sp,
        fontWeight  = FontWeight.Normal,
    ),
    titleSmall = TextStyle(
        fontFamily  = FontFamily.Default,
        fontSize    = 16.sp,
        lineHeight  = 24.sp,
        fontWeight  = FontWeight.SemiBold,
    ),
    titleMedium = TextStyle(
        fontFamily  = FontFamily.Default,
        fontSize    = 18.sp,
        lineHeight  = 26.sp,
        fontWeight  = FontWeight.SemiBold,
    ),
    headlineSmall = TextStyle(
        fontFamily  = FontFamily.Default,
        fontSize    = 22.sp,
        lineHeight  = 28.sp,
        fontWeight  = FontWeight.SemiBold,
    ),
    headlineMedium = TextStyle(
        fontFamily  = FontFamily.Default,
        fontSize    = 28.sp,
        lineHeight  = 34.sp,
        fontWeight  = FontWeight.Bold,
    ),
)

// Monospace text style for OutputArea lines
val OutputLineStyle = TextStyle(
    fontFamily = MonospaceFamily,
    fontSize   = 11.sp,
    lineHeight = 16.sp,
    fontWeight = FontWeight.Normal,
)
