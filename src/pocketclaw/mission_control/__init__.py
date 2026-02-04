"""Mission Control - Multi-agent orchestration for PocketPaw.

Created: 2026-02-05

Mission Control provides a shared workspace where multiple AI agents
can work together like a team. Features:

- Agent profiles with roles, status, and capabilities
- Task management with lifecycle (inbox -> assigned -> in_progress -> review -> done)
- Message threads for discussions on tasks
- Activity feed for real-time visibility
- Document storage for deliverables
- Notification system with @mentions
- Heartbeat system for agent status tracking

Usage:
    from pocketclaw.mission_control import get_mission_control_manager

    manager = get_mission_control_manager()

    # Create an agent
    agent = await manager.create_agent(
        name="Jarvis",
        role="Squad Lead",
        description="Coordinates the team and handles requests"
    )

    # Create a task
    task = await manager.create_task(
        title="Research competitors",
        description="Analyze top 5 competitors",
        assignee_ids=[agent.id]
    )

    # Post a message
    await manager.post_message(
        task_id=task.id,
        from_agent_id=agent.id,
        content="Starting research now. @all please share any insights."
    )

    # Get activity feed
    activities = await manager.get_activity_feed()
"""

# Models
# Manager
from pocketclaw.mission_control.manager import (
    MissionControlManager,
    get_mission_control_manager,
    reset_mission_control_manager,
)
from pocketclaw.mission_control.models import (
    Activity,
    ActivityType,
    AgentLevel,
    AgentProfile,
    AgentStatus,
    Document,
    DocumentType,
    Message,
    Notification,
    Task,
    TaskPriority,
    TaskStatus,
)

# Store
from pocketclaw.mission_control.store import (
    FileMissionControlStore,
    get_mission_control_store,
    reset_mission_control_store,
)

__all__ = [
    # Models
    "AgentProfile",
    "AgentStatus",
    "AgentLevel",
    "Task",
    "TaskStatus",
    "TaskPriority",
    "Message",
    "Activity",
    "ActivityType",
    "Document",
    "DocumentType",
    "Notification",
    # Store
    "FileMissionControlStore",
    "get_mission_control_store",
    "reset_mission_control_store",
    # Manager
    "MissionControlManager",
    "get_mission_control_manager",
    "reset_mission_control_manager",
]
