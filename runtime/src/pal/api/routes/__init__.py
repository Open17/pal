"""API route tables."""

from . import bots, conversations, displays, events, memory, system

ROUTE_TABLES = (
    system.routes,
    bots.routes,
    conversations.routes,
    memory.routes,
    displays.routes,
    events.routes,
)
