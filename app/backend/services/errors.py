"""Reusable, user-safe service exceptions."""


class ServiceError(Exception):
    """Base error carrying an HTTP-safe code and status."""

    code = "SERVICE_ERROR"
    status_code = 400

    def __init__(self, message, *, code=None, status_code=None):
        super().__init__(message)
        self.message = message
        self.code = code or self.code
        self.status_code = status_code or self.status_code


class ValidationServiceError(ServiceError):
    code = "VALIDATION_ERROR"
    status_code = 400


class AuthenticationRequiredError(ServiceError):
    code = "AUTHENTICATION_REQUIRED"
    status_code = 401


class InvalidCredentialsError(ServiceError):
    code = "INVALID_CREDENTIALS"
    status_code = 401


class ForbiddenError(ServiceError):
    code = "FORBIDDEN"
    status_code = 403


class NotFoundError(ServiceError):
    code = "NOT_FOUND"
    status_code = 404


class ConflictError(ServiceError):
    code = "CONFLICT"
    status_code = 409


class UpstreamServiceError(ServiceError):
    code = "UPSTREAM_UNAVAILABLE"
    status_code = 503
