class DemoError(Exception):
    """A user-facing demo failure. The graph did not approve anything."""

    def __init__(self, message: str, exit_code: int = 1) -> None:
        super().__init__(message)
        self.exit_code = exit_code
