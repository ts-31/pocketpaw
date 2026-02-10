"""
Builder for assembling the full agent context.
Created: 2026-02-02
Updated: 2026-02-07 - Semantic context injection for mem0 backend
"""

from pocketclaw.bootstrap.default_provider import DefaultBootstrapProvider
from pocketclaw.bootstrap.protocol import BootstrapProviderProtocol
from pocketclaw.memory.manager import MemoryManager, get_memory_manager


class AgentContextBuilder:
    """
    Assembles the final system prompt by combining:
    1. Static Identity (Bootstrap)
    2. Dynamic Memory (MemoryManager)
    3. Current State (e.g., date/time, active tasks)
    """

    def __init__(
        self,
        bootstrap_provider: BootstrapProviderProtocol | None = None,
        memory_manager: MemoryManager | None = None,
    ):
        self.bootstrap = bootstrap_provider or DefaultBootstrapProvider()
        self.memory = memory_manager or get_memory_manager()

    async def build_system_prompt(
        self, include_memory: bool = True, user_query: str | None = None
    ) -> str:
        """Build the complete system prompt.

        Args:
            include_memory: Whether to include memory context.
            user_query: Current user message for semantic memory search (mem0).
        """
        # 1. Load static identity
        context = await self.bootstrap.get_context()
        base_prompt = context.to_system_prompt()

        parts = [base_prompt]

        # 2. Inject memory context
        if include_memory:
            if user_query:
                # Use semantic search if mem0 backend and query available
                memory_context = await self.memory.get_semantic_context(user_query)
            else:
                memory_context = await self.memory.get_context_for_agent()
            if memory_context:
                parts.append(
                    "\n# Memory Context (already loaded — use this directly, "
                    "do NOT call recall unless you need something not listed here)\n"
                    + memory_context
                )

        return "\n\n".join(parts)
