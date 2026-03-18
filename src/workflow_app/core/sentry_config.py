"""
Sentry error tracking for Workflow App (desktop).

Call init_sentry() once at startup (before MainWindow).
Uses LoggingIntegration to capture WARNING+ log entries as breadcrumbs
and SqlalchemyIntegration for query tracing.
"""

from __future__ import annotations

import os


def init_sentry() -> None:
    """Initialise Sentry SDK if SENTRY_DSN is set.

    Safe to call when DSN is absent — silently becomes a no-op.
    """
    dsn = os.getenv("SENTRY_DSN")
    if not dsn:
        return

    try:
        import sentry_sdk
        from sentry_sdk.integrations.logging import LoggingIntegration
        from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration
    except ImportError:
        # sentry-sdk not installed — skip silently
        return

    import logging

    sentry_logging = LoggingIntegration(
        level=logging.WARNING,        # breadcrumbs at WARNING+
        event_level=logging.ERROR,    # send event to Sentry at ERROR+
    )

    env = os.getenv("PYTHON_ENV", "development")

    sentry_sdk.init(
        dsn=dsn,
        integrations=[sentry_logging, SqlalchemyIntegration()],
        traces_sample_rate=0.1 if env == "production" else 0.0,
        environment=env,
        release=os.getenv("APP_VERSION", "0.1.0"),
        # Desktop apps: attach user context via sentry_sdk.set_user() after login
    )
