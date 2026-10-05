"""Exception hierarchy. Every expected failure derives from AgentError so the UI can show it cleanly."""


class AgentError(Exception):
    """Base class for all expected agent failures."""


class ToolError(AgentError):
    """A codebase tool could not complete its operation."""


class SecurityError(ToolError):
    """An operation was rejected by the workspace security policy."""


class PatchError(ToolError):
    """A proposed patch is invalid or cannot be applied."""


class LLMError(AgentError):
    """The LLM provider failed or returned an unusable response."""
