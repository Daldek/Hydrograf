"""The result envelope of every command, ``hydrograf-result/1`` (AGI-4.2, ADR-091).

A command's run gives an :class:`Outcome`: its domain document (``hydrograf-<kind>/1``)
and its notices. :func:`envelope` wraps it as the synchronous route answers it and as
``GET /api/v1/jobs/<id>/result`` answers a job of it: ``result`` is the document with
its ``schema`` as the first member, ``notices`` the ``{level, code, message}`` notices
of the run. :func:`document_model` and :func:`envelope_model` give the OpenAPI document
the shape of each command's answer.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final, Literal

from pydantic import BaseModel, Field, create_model

from core.version import get_version

TOOL: Final = "hydrograf"
RESULT_SCHEMA: Final = "hydrograf-result/1"

Status = Literal["ok", "partial", "failed", "cancelled"]


class Notice(BaseModel):
    """A notice about a result (AGI-4.2)."""

    level: Literal["info", "warning"] = Field(
        ..., description="warning: the result needs the person's attention"
    )
    code: str = Field(
        ...,
        description="What the notice is about: outlet_far_from_point of a watershed, "
        "the code of Hydrolog's notice of a hydrograph (hydrolog.catalog.NOTICES)",
    )
    message: str = Field(..., description="Polish text of the notice")


@dataclass(frozen=True)
class Outcome:
    """What the run of a command gives.

    Attributes
    ----------
    document : BaseModel or Mapping[str, Any]
        The domain document, without its ``schema``, which the catalog names.
    notices : Sequence[BaseModel]
        Notices with ``level``, ``code`` and ``message``.
    cache_control : str or None
        ``Cache-Control`` of the synchronous answer, None for none.
    """

    document: BaseModel | Mapping[str, Any]
    notices: Sequence[BaseModel] = ()
    cache_control: str | None = None


def envelope(
    command: str, schema: str, outcome: Outcome | None, *, status: Status = "ok"
) -> dict[str, Any]:
    """Return the envelope ``hydrograf-result/1`` of a run.

    Parameters
    ----------
    command : str
        Catalog name of the command, e.g. ``"watershed delineate"``.
    schema : str
        The id of its domain document, e.g. ``"hydrograf-watershed/1"``.
    outcome : Outcome or None
        What the run gave; None when it produced nothing (a cancelled job).
    status : {"ok", "partial", "failed", "cancelled"}, optional
        The overall outcome.

    Returns
    -------
    dict[str, Any]
        The envelope, its ``result`` serialised as the routes answer (JSON values,
        members by their aliases).
    """
    result: dict[str, Any] | None = None
    notices: list[dict[str, Any]] = []
    if outcome is not None:
        document = outcome.document
        body = (
            document.model_dump(mode="json", by_alias=True)
            if isinstance(document, BaseModel)
            else dict(document)
        )
        result = {"schema": schema, **body}
        notices = [notice.model_dump(mode="json") for notice in outcome.notices]
    return {
        "schema": RESULT_SCHEMA,
        "tool": TOOL,
        "version": get_version(),
        "command": command,
        "check": False,
        "status": status,
        "result": result,
        "notices": notices,
    }


def _constant(value: str, description: str) -> Any:
    return Field(value, alias="schema", description=description, examples=[value])


class Envelope(BaseModel):
    """The result envelope ``hydrograf-result/1`` of a command (AGI-4.2)."""

    schema_: str = _constant(RESULT_SCHEMA, "`hydrograf-result/1`")
    tool: str = Field(TOOL, description="`hydrograf`")
    version: str = Field(..., description="The version of Hydrograf")
    command: str = Field(..., description="The catalog name of the command")
    check: bool = Field(False, description="Always false: no command plans")
    status: Status = Field(
        ...,
        description="ok; cancelled for a job cancelled before it ended (`result` null)",
    )
    result: dict[str, Any] | None = Field(
        ..., description="The domain document `hydrograf-<kind>/1`"
    )
    notices: list[Notice] = Field(
        default_factory=list, description="Notices about the result; empty without"
    )


def document_model(name: str, base: type[BaseModel], schema: str) -> type[BaseModel]:
    """Return ``base`` with its ``schema`` member, for the OpenAPI document."""
    model: type[BaseModel] = create_model(
        name,
        __base__=base,
        __doc__=f"{base.__doc__ or name}\n\nThe domain document `{schema}`.",
        schema_=(str, _constant(schema, f"`{schema}`")),
    )
    return model


def envelope_model(name: str, document: type[BaseModel]) -> type[BaseModel]:
    """Return the envelope whose ``result`` is ``document``, for the OpenAPI doc."""
    # A union built at run time, which create_model takes as the field's type
    optional: Any = document | None
    model: type[BaseModel] = create_model(
        name,
        __base__=Envelope,
        result=(optional, Field(..., description="The domain document")),
    )
    return model
