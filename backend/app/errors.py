"""Structured API errors. Messages are written for the product UI."""


class APIError(Exception):
    def __init__(self, status_code: int, code: str, message: str):
        self.status_code = status_code
        self.code = code
        self.message = message
        super().__init__(message)


class ProviderError(Exception):
    def __init__(self, message: str, *, retryable: bool = True):
        self.message = message
        self.retryable = retryable
        super().__init__(message)
