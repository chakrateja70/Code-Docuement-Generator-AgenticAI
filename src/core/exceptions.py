from fastapi import HTTPException
from starlette.status import (
    HTTP_400_BAD_REQUEST,
    HTTP_401_UNAUTHORIZED,
    HTTP_403_FORBIDDEN,
    HTTP_404_NOT_FOUND,
    HTTP_409_CONFLICT,
    HTTP_500_INTERNAL_SERVER_ERROR,
)

# Centralized status messages
STATUS_MESSAGES = {
    HTTP_400_BAD_REQUEST: "Bad Request",
    HTTP_401_UNAUTHORIZED: "Unauthorized",
    HTTP_403_FORBIDDEN: "Forbidden",
    HTTP_404_NOT_FOUND: "Not Found",
    HTTP_409_CONFLICT: "Conflict",
    HTTP_500_INTERNAL_SERVER_ERROR: "Internal Server Error",
}


class BaseAPIException(HTTPException):
    """Base exception class for all API exceptions."""

    def __init__(self, status_code: int, error_message: str):
        status_message = STATUS_MESSAGES.get(status_code, "Error")
        super().__init__(
            status_code=status_code,
            detail={
                "statusCode": status_code,
                "statusMessage": status_message,
                "errorMessage": error_message,
            },
        )


class BadRequestAPIException(BaseAPIException):
    def __init__(self, error_message: str = "Bad request"):
        super().__init__(HTTP_400_BAD_REQUEST, error_message)


class UnauthorizedAPIException(BaseAPIException):
    def __init__(self, error_message: str = "Unauthorized"):
        super().__init__(HTTP_401_UNAUTHORIZED, error_message)


class ForbiddenAPIException(BaseAPIException):
    def __init__(self, error_message: str = "Forbidden"):
        super().__init__(HTTP_403_FORBIDDEN, error_message)


class NotFoundAPIException(BaseAPIException):
    def __init__(self, error_message: str = "Not found"):
        super().__init__(HTTP_404_NOT_FOUND, error_message)


class ConflictAPIException(BaseAPIException):
    def __init__(self, error_message: str = "Conflict"):
        super().__init__(HTTP_409_CONFLICT, error_message)


class InternalServerAPIException(BaseAPIException):
    def __init__(self, error_message: str = "Internal server error"):
        super().__init__(HTTP_500_INTERNAL_SERVER_ERROR, error_message)


# ---------------------------------------------------------------------------
# Ingestion-specific exceptions
# ---------------------------------------------------------------------------


class InvalidGitUrlException(BadRequestAPIException):
    """Raised when the provided Git URL is malformed or unsupported."""

    def __init__(self, error_message: str = "Invalid or unsupported Git repository URL."):
        super().__init__(error_message)


class PrivateRepoAuthException(UnauthorizedAPIException):
    """Raised when a private repo is requested without valid credentials."""

    def __init__(self, error_message: str = "Authentication failed for the private repository."):
        super().__init__(error_message)


class RepoCloneException(InternalServerAPIException):
    """Raised when cloning the repository fails unexpectedly."""

    def __init__(self, error_message: str = "Failed to clone the repository."):
        super().__init__(error_message)


class InvalidZipFileException(BadRequestAPIException):
    """Raised when the uploaded file is not a valid/usable zip archive."""

    def __init__(self, error_message: str = "Invalid or corrupt zip file."):
        super().__init__(error_message)


class ZipExtractionException(InternalServerAPIException):
    """Raised when extracting the uploaded zip fails unexpectedly."""

    def __init__(self, error_message: str = "Failed to extract the zip file."):
        super().__init__(error_message)
