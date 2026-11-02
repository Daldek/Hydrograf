"""Errors of Hydrograf (DEV-11.1, ERR-1, ERR-4).

``HydrografError`` is the one base exception: every error carries exactly one code of
the shared registry (``core._errors``), a message, a hint when a fix is known, and
JSON-compatible ``details`` whose ``reason`` is the project's own cause in snake_case
English (ERR-1). Each subclass selects a default code. The texts come from the message
catalogue (``core.messages``), so one error has an English and a Polish wording; the API
answers with ``application/problem+json`` in ``api.errors``.
"""

from typing import Any, ClassVar

from core._errors import BY_CODE, ErrorCodeName
from core.messages import MESSAGES, Language, render


class HydrografError(Exception):
    """Base of the errors of Hydrograf.

    Parameters
    ----------
    message_id : str
        English ID of the message in the catalogue ``core.messages``.
    reason : str
        The project's cause in snake_case English, stored as ``details["reason"]``.
    code : str or None, optional
        Registry code; the default code of the class when omitted.
    **details : Any
        JSON-compatible context of the error; it also fills the ``{fields}`` of the
        message and of its hint.

    Attributes
    ----------
    code : str
        Registry code (ERR section 2) with an HTTP status.
    message : str
        English description of what happened.
    hint : str or None
        English line telling how to fix it.
    details : dict[str, Any]
        ``reason`` and the context of the error.
    message_id : str
        ID of the message in the catalogue.

    Raises
    ------
    ValueError
        When the code is not a code of the registry that has an HTTP status, or the
        message ID is not in the catalogue.
    """

    default_code: ClassVar[ErrorCodeName] = "internal_error"

    def __init__(
        self,
        message_id: str,
        *,
        reason: str,
        code: ErrorCodeName | None = None,
        **details: Any,
    ) -> None:
        chosen = code or self.default_code
        entry = BY_CODE.get(chosen)
        if entry is None or entry.http_status is None:
            raise ValueError(f"{chosen!r} is not a registry code with an HTTP status")
        if message_id not in MESSAGES:
            raise ValueError(f"{message_id!r} is not in the message catalogue")
        self.message_id = message_id
        self.code: ErrorCodeName = chosen
        self.details: dict[str, Any] = {"reason": reason, **details}
        self.message = self.text("en")
        self.hint = self.hint_text("en")
        super().__init__(self.message)

    def text(self, lang: Language = "en") -> str:
        """Return the description in ``lang``."""
        return render(MESSAGES[self.message_id].text(lang), self.details)

    def hint_text(self, lang: Language = "en") -> str | None:
        """Return the hint in ``lang``, or None when the message has none."""
        hint = MESSAGES[self.message_id].hint(lang)
        return None if hint is None else render(hint, self.details)

    @property
    def http_status(self) -> int:
        """int: HTTP status of the code (ERR section 2)."""
        return BY_CODE[self.code].http_status or 500


class InvalidRequestError(HydrografError):
    """A value of the request is wrong or not allowed (``validation_error``)."""

    default_code: ClassVar[ErrorCodeName] = "validation_error"


class NotFoundError(HydrografError):
    """The referenced resource does not exist (``not_found``)."""

    default_code: ClassVar[ErrorCodeName] = "not_found"


class NoDataError(HydrografError):
    """The request is valid but there is no data for it (``no_data``)."""

    default_code: ClassVar[ErrorCodeName] = "no_data"


class ConflictError(HydrografError):
    """The request conflicts with the current state (``conflict``)."""

    default_code: ClassVar[ErrorCodeName] = "conflict"


class UnauthorizedError(HydrografError):
    """The credentials are missing or invalid (``unauthorized``)."""

    default_code: ClassVar[ErrorCodeName] = "unauthorized"


class ForbiddenError(HydrografError):
    """The request reaches outside what is allowed (``forbidden``)."""

    default_code: ClassVar[ErrorCodeName] = "forbidden"


class CalculationError(HydrografError):
    """The input is valid but no result can be computed (``calculation_error``)."""

    default_code: ClassVar[ErrorCodeName] = "calculation_error"


class UnsupportedError(HydrografError):
    """The request is valid but outside the scope of the method (``unsupported``)."""

    default_code: ClassVar[ErrorCodeName] = "unsupported"


class StoreUnavailableError(HydrografError):
    """The database, the graph or a data file cannot be used (``store_unavailable``)."""

    default_code: ClassVar[ErrorCodeName] = "store_unavailable"


class FileOperationError(HydrografError):
    """Reading or writing a file failed (``io_error``)."""

    default_code: ClassVar[ErrorCodeName] = "io_error"


class InternalError(HydrografError):
    """A defect or an unexpected failure (``internal_error``)."""

    default_code: ClassVar[ErrorCodeName] = "internal_error"
