"""
SQLAlchemy models for Workflow App (module-02/TASK-2).

TODO: Implement backend — module-02/TASK-2 (auto-flow execute)

Models to implement:
  - PipelineExecution: id, project_name, status (PipelineStatus), started_at,
                       completed_at, permission_mode
  - CommandExecution:  id, pipeline_id, name, model, interaction_type, status
                       (CommandStatus), position, started_at, elapsed_s, output_text
  - ExecutionLog:      id, command_id, timestamp, text_chunk
  - Template:          id, name, commands_json, is_factory, sha256, created_at
  - AppState:          singleton key-value table (last_project_path,
                       permission_mode, prefs_json)
"""

from __future__ import annotations

# Placeholder — SQLAlchemy Base will be defined here in module-02/TASK-2
# from sqlalchemy.orm import DeclarativeBase
# class Base(DeclarativeBase): pass

# TODO: Implement backend — module-02/TASK-2 (auto-flow execute)
