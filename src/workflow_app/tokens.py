"""
D19 Graphite Amber — Design tokens as Python dataclasses.

Usage:
    from workflow_app.tokens import COLORS, TYPOGRAPHY, SPACING
    bg = COLORS.background  # "#18181B"
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ColorTokens:
    background: str = "#18181B"
    surface: str = "#27272A"
    surface_elevated: str = "#3F3F46"
    border: str = "#3F3F46"
    border_subtle: str = "#52525B"

    primary: str = "#FBBF24"
    primary_hover: str = "#FDE68A"
    primary_pressed: str = "#F59E0B"
    primary_muted: str = "#78350F"

    text: str = "#FAFAFA"
    text_secondary: str = "#A1A1AA"
    text_muted: str = "#71717A"
    text_disabled: str = "#52525B"

    danger: str = "#FB7185"
    success: str = "#34D399"
    warning: str = "#F97316"
    info: str = "#38BDF8"

    # Status
    status_pendente: str = "#A1A1AA"
    status_executando: str = "#38BDF8"
    status_concluido: str = "#34D399"
    status_erro: str = "#FB7185"
    status_pulado: str = "#71717A"
    status_incerto: str = "#F97316"

    # Model badges
    model_opus: str = "#7C3AED"
    model_sonnet: str = "#2563EB"
    model_haiku: str = "#059669"


@dataclass(frozen=True)
class TypographyTokens:
    font_ui: str = "Inter"
    font_mono: str = "JetBrains Mono"
    size_xs: int = 10
    size_sm: int = 11
    size_base: int = 13
    size_md: int = 14
    size_lg: int = 16
    size_xl: int = 18
    size_2xl: int = 22


@dataclass(frozen=True)
class SpacingTokens:
    xs: int = 4
    sm: int = 8
    md: int = 12
    lg: int = 16
    xl: int = 24


COLORS = ColorTokens()
TYPOGRAPHY = TypographyTokens()
SPACING = SpacingTokens()
