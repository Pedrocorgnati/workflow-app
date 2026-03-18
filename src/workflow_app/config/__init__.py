"""Config package — project.json parsing, detection, and app state."""

from workflow_app.config.app_state import AppState, app_state
from workflow_app.config.config_bar import ConfigBar
from workflow_app.config.config_parser import PipelineConfig, detect_config, parse_config

__all__ = [
    "AppState",
    "app_state",
    "ConfigBar",
    "PipelineConfig",
    "detect_config",
    "parse_config",
]
