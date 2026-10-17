"""Safe, typed application failures; internal exception detail never reaches clients."""


class AppError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.status_code = status
        self.code = code
        self.message = message
