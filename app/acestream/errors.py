class EngineError(Exception):
    """Base class for every failure talking to the Acestream engine."""


class EngineUnavailableError(EngineError):
    """The engine cannot be reached (not running, wrong URL, connection refused)."""


class EngineTimeoutError(EngineError):
    """The engine did not answer within the configured timeout."""


class EngineProtocolError(EngineError):
    """The engine answered, but not in the shape documented in docs/engine-api.md."""


class ContentNotFoundError(EngineError):
    """The engine could not load the content (unknown or malformed Content ID)."""

    def __init__(self, content_id: str):
        super().__init__(f"engine could not load content: {content_id}")
        self.content_id = content_id
