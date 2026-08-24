from shared.exceptions import ForbiddenError, NotFoundError, ValidationError


class ReservationNotFoundError(NotFoundError): pass
class ReservationAccessError(ForbiddenError): pass
class ReservationStateError(ValidationError): pass
