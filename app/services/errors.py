"""Domain errors raised by the service layer."""


class ServiceError(Exception):
    pass


class NotFoundError(ServiceError):
    pass


class DuplicateError(ServiceError):
    pass


class CategoryInUseError(ServiceError):
    pass


class ValidationError(ServiceError, ValueError):
    pass
