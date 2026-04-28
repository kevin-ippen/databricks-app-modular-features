"""
Conversation Memory Feature

Persistent conversation history and automatic summarization.
Database-agnostic via dependency-injected connection factory.
"""
from .memory import MemoryLayer

__all__ = ["MemoryLayer"]
