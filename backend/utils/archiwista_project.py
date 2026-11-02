"""The project file of Archiwista, read strictly for a bootstrap from a set (ADR-067).

A project of Archiwista (its A-ADR-049) is a directory holding the project file
``archiwista-project.json`` of the schema ``archiwista-project/1``: the project's area
(a GeoJSON file below ``obszary/`` with the SHA-256 of its bytes), one store root per
producer and the sets (the member ``groups``) of pins. A pin names a version of a
producer's store by its path relative to the store root, with the SHA-256 and the size
of the file. A set is open (``state: "open"``, being built) or closed (``"closed"``; a
set without ``state`` was written before sets had one and is closed); closing it
records ``closed_at``, ``closed_by`` and ``pins_sha256``, the digest of its pins
(:func:`pins_digest`), and a closed set does not change until it is opened again.

Hydrograf never writes a project. :func:`read_project` reads the members it uses and
ignores the others, as the format requires; :func:`read_set` selects a closed set,
:func:`project_area` checks the area file, :func:`kartograf_root` finds the Kartograf
store of the pins and :func:`verify_pins` checks every pinned file. Each refusal is a
:class:`core.errors.HydrografError` with a code of the shared registry, a ``reason``
of ADR-067 and a hint that names the action of Archiwista that fixes it.
"""

import hashlib
import json
import os
import re
import stat
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath

from core.errors import (
    ConflictError,
    FileOperationError,
    InvalidDataError,
    InvalidRequestError,
    NotFoundError,
    StoreUnavailableError,
    UnsupportedError,
)
from utils.kartograf_store import describe_error, shared_store_root

PROJECT_FILE = "archiwista-project.json"
PROJECT_SCHEMA = "archiwista-project/1"
AREAS_DIR = "obszary"
# The producer whose store Hydrograf reads.
KARTOGRAF = "kartograf"
# Archiwista's own limits of a project file and of a set's name.
MAX_PROJECT_FILE_BYTES = 32 * 1024**2
MAX_SET_NAME_CHARS = 80

_SCHEMA = re.compile(r"archiwista-project/([1-9][0-9]{0,8})")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_PRODUCER = re.compile(r"[a-z][a-z0-9_]{0,31}")
_TIME = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z")
_STATES = ("open", "closed")


@dataclass(frozen=True)
class Pin:
    """A pinned version: its file relative to the producer's store and its digest."""

    producer: str
    version: str
    sha256: str
    size_bytes: int


@dataclass(frozen=True)
class PinSet:
    """A set of a project (a ``groups`` entry of the file).

    Attributes
    ----------
    name : str
        As the file holds it (NFC, trimmed).
    closed : bool
        ``state`` is ``closed`` or absent; False for ``open``.
    closed_at, closed_by : str or None
        When and by whom the set was closed, when the file records it.
    pins_sha256 : str or None
        The digest written on close (:func:`pins_digest`), when the file holds one.
    pins : tuple[Pin, ...]
        Every pin, of any producer, in the order of the file.
    """

    name: str
    closed: bool
    closed_at: str | None
    closed_by: str | None
    pins_sha256: str | None
    pins: tuple[Pin, ...]


@dataclass(frozen=True)
class AreaRef:
    """The project's area: its file relative to the project and the file's SHA-256."""

    path: str
    sha256: str


@dataclass(frozen=True)
class Project:
    """What Hydrograf reads of a project file.

    Attributes
    ----------
    directory : Path
        The project directory: relative paths of the file start here.
    name : str
        The project's name.
    area : AreaRef or None
        The area, None when the project has none.
    stores : Mapping[str, str]
        Producer to its store root as written: absolute, or relative to ``directory``.
    sets : tuple[PinSet, ...]
        In the order of the file.
    """

    directory: Path
    name: str
    area: AreaRef | None
    stores: Mapping[str, str]
    sets: tuple[PinSet, ...]


def clean_name(text: str) -> str:
    """Return a name as Archiwista compares it: NFC without surrounding white space."""
    return unicodedata.normalize("NFC", text).strip()


def pins_digest(pins: Iterable[Pin]) -> str:
    r"""Return ``pins_sha256`` of a set: the digest Archiwista writes when it closes it.

    The lowercase hex SHA-256 of the UTF-8 lines ``<producer>\t<version>\t<sha256>\n``,
    one per pin, sorted by producer and version (code points). A field never holds a
    tab or a line break, so the lines cannot be read two ways.
    """
    lines = sorted((pin.producer, pin.version, pin.sha256) for pin in pins)
    text = "".join(
        f"{producer}\t{version}\t{sha256}\n" for producer, version, sha256 in lines
    )
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def read_project(path: Path) -> Project:
    """Read a project from its directory or from its ``archiwista-project.json``.

    Raises
    ------
    NotFoundError
        ``project_file_missing``.
    FileOperationError
        ``project_file_unreadable``: the file exists and cannot be read.
    UnsupportedError
        ``project_schema_unsupported``: ``archiwista-project/<n>`` with ``n`` above 1.
    InvalidDataError
        ``project_file_invalid``: a member Hydrograf reads breaks its rule
        (``details``: ``pointer``, the JSON pointer, and ``rule``).
    """
    file = path if path.name == PROJECT_FILE and path.is_file() else path / PROJECT_FILE
    directory = file.parent
    try:
        data = file.read_bytes()
    except (FileNotFoundError, NotADirectoryError):
        raise NotFoundError(
            "project_file_missing", reason="project_file_missing", path=str(directory)
        ) from None
    except OSError as error:
        raise FileOperationError(
            "file_unreadable",
            reason="project_file_unreadable",
            path=str(file),
            cause=error.strerror or str(error),
        ) from error
    if len(data) > MAX_PROJECT_FILE_BYTES:
        raise _invalid(file, "", "file_size")
    try:
        document = json.loads(data.decode("utf-8"))
    except ValueError:
        raise _invalid(file, "", "json") from None
    return _project(file, directory, document)


def read_set(project: Project, name: str) -> PinSet:
    """Return the closed set ``name`` of a project (names compared case-folded).

    Raises
    ------
    NotFoundError
        ``set_not_found`` (``details["sets"]``: the names of the project's sets).
    ConflictError
        ``set_open``: the set is being built in Archiwista.
    InvalidDataError
        ``set_digest_mismatch``: the file holds a ``pins_sha256`` that its pins do not
        give, so it was changed outside Archiwista.
    """
    wanted = clean_name(name).casefold()
    found = next(
        (item for item in project.sets if item.name.casefold() == wanted), None
    )
    if found is None:
        raise NotFoundError(
            "set_not_found",
            reason="set_not_found",
            project=project.name,
            name=name,
            sets=[item.name for item in project.sets],
        )
    if not found.closed:
        raise ConflictError("set_open", reason="set_open", name=found.name)
    if found.pins_sha256 is not None:
        actual = pins_digest(found.pins)
        if actual != found.pins_sha256:
            raise InvalidDataError(
                "set_digest_mismatch",
                reason="set_digest_mismatch",
                name=found.name,
                expected=found.pins_sha256,
                actual=actual,
            )
    return found


def project_area(project: Project) -> Path:
    """Return the project's area file after checking its SHA-256.

    Raises
    ------
    NotFoundError
        ``area_missing``: the project has no area, or its file is gone.
    InvalidDataError
        ``area_changed``: the file's SHA-256 is not the recorded one.
    FileOperationError
        ``area_unreadable``: the file cannot be read.
    """
    if project.area is None:
        raise NotFoundError(
            "project_area_unset", reason="area_missing", project=project.name
        )
    path = project.directory / project.area.path
    try:
        actual = _file_sha256(path)
    except (FileNotFoundError, NotADirectoryError, IsADirectoryError):
        raise NotFoundError(
            "project_area_missing", reason="area_missing", path=str(path)
        ) from None
    except OSError as error:
        raise FileOperationError(
            "file_unreadable",
            reason="area_unreadable",
            path=str(path),
            cause=error.strerror or str(error),
        ) from error
    if actual != project.area.sha256:
        raise InvalidDataError(
            "project_area_changed",
            reason="area_changed",
            path=str(path),
            expected=project.area.sha256,
            actual=actual,
        )
    return path


def kartograf_root(project: Project) -> Path:
    """Return the Kartograf store of the project's pins.

    The root of the file (absolute, or relative to the project directory) must be a
    store with its marker, as Kartograf judges it (``store_state`` is ``marked``).
    When ``HYDROGRAF_KARTOGRAF_ROOT`` is set, it must name the same directory.

    Raises
    ------
    StoreUnavailableError
        ``store_missing``: no Kartograf store in the file, or a root that is not a
        marked store (missing, empty, without a marker, unreadable).
    InvalidRequestError
        ``store_mismatch``: the root is not the store of ``HYDROGRAF_KARTOGRAF_ROOT``.
    """
    from kartograf import KartografError, store_state

    written = project.stores.get(KARTOGRAF)
    if written is None:
        raise StoreUnavailableError(
            "project_store_unset", reason="store_missing", project=project.name
        )
    root = Path(written)
    if not root.is_absolute():
        root = project.directory / root
    try:
        state = store_state(root)
    except (KartografError, OSError) as error:
        raise StoreUnavailableError(
            "project_store_unusable",
            reason="store_missing",
            root=str(root),
            state=describe_error(error),
        ) from error
    if state != "marked":
        raise StoreUnavailableError(
            "project_store_unusable",
            reason="store_missing",
            root=str(root),
            state=state,
        )
    shared = shared_store_root()
    if shared is not None and not _same_directory(root, shared):
        raise InvalidRequestError(
            "project_store_mismatch",
            reason="store_mismatch",
            root=str(root),
            shared=str(shared),
        )
    return root


def verify_pins(root: Path, pins: Sequence[Pin], set_name: str) -> None:
    """Check that every pinned file is in the store with its size and SHA-256.

    Every file is read whole. A missing file is reported before an unreadable one,
    and both before a changed one; ``details["pins"]`` lists the versions.

    Raises
    ------
    NotFoundError
        ``pin_missing``.
    FileOperationError
        ``pin_unreadable``.
    InvalidDataError
        ``pin_changed``: another size or SHA-256.
    """
    missing: list[str] = []
    unreadable: list[str] = []
    changed: list[str] = []
    cause = ""
    for pin in pins:
        path = root / pin.version
        try:
            info = path.stat()
            if not stat.S_ISREG(info.st_mode):
                missing.append(pin.version)
            elif info.st_size != pin.size_bytes or _file_sha256(path) != pin.sha256:
                changed.append(pin.version)
        except (FileNotFoundError, NotADirectoryError):
            missing.append(pin.version)
        except OSError as error:
            unreadable.append(pin.version)
            cause = cause or f"{pin.version}: {error.strerror or error}"
    if missing:
        raise NotFoundError(
            "pins_missing",
            reason="pin_missing",
            name=set_name,
            root=str(root),
            count=len(missing),
            pins=missing,
        )
    if unreadable:
        raise FileOperationError(
            "pins_unreadable",
            reason="pin_unreadable",
            name=set_name,
            count=len(unreadable),
            cause=cause,
            pins=unreadable,
        )
    if changed:
        raise InvalidDataError(
            "pins_changed",
            reason="pin_changed",
            name=set_name,
            count=len(changed),
            pins=changed,
        )


def _file_sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _same_directory(first: Path, second: Path) -> bool:
    try:
        return os.path.samefile(first, second)
    except OSError:
        return False


def _invalid(file: Path, pointer: str, rule: str) -> InvalidDataError:
    return InvalidDataError(
        "project_file_invalid",
        reason="project_file_invalid",
        path=str(file),
        pointer=pointer,
        rule=rule,
    )


def _project(file: Path, directory: Path, document: object) -> Project:
    reader = _Reader(file)
    root = reader.mapping(document, "")
    schema = root.get("schema")
    if schema != PROJECT_SCHEMA:
        found = _SCHEMA.fullmatch(schema) if isinstance(schema, str) else None
        if found is not None and int(found[1]) > 1:
            raise UnsupportedError(
                "project_schema_unsupported",
                reason="project_schema_unsupported",
                schema=schema,
            )
        raise reader.invalid("/schema", "required" if schema is None else "schema")
    return Project(
        directory=directory,
        name=reader.name(root, "/name", "name", None),
        area=reader.area(root.get("area")),
        stores=reader.stores(reader.array(root, "/stores")),
        sets=reader.sets(reader.array(root, "/groups")),
    )


class _Reader:
    """The rules of the members Hydrograf reads, as Archiwista's reader states them."""

    def __init__(self, file: Path) -> None:
        self.file = file

    def invalid(self, pointer: str, rule: str) -> InvalidDataError:
        return _invalid(self.file, pointer, rule)

    def mapping(self, value: object, pointer: str) -> Mapping[str, object]:
        if not isinstance(value, dict):
            raise self.invalid(pointer, "object")
        return value

    def member(self, parent: Mapping[str, object], pointer: str) -> object:
        name = pointer.rsplit("/", 1)[-1]
        if name not in parent:
            raise self.invalid(pointer, "required")
        return parent[name]

    def array(self, parent: Mapping[str, object], pointer: str) -> list[object]:
        value = self.member(parent, pointer)
        if not isinstance(value, list):
            raise self.invalid(pointer, "array")
        return value

    def name(
        self, parent: Mapping[str, object], pointer: str, rule: str, limit: int | None
    ) -> str:
        value = self.member(parent, pointer)
        if not isinstance(value, str):
            raise self.invalid(pointer, rule)
        name = clean_name(value)
        if not name or (limit is not None and len(name) > limit) or not _plain(name):
            raise self.invalid(pointer, rule)
        return name

    def sha256(self, parent: Mapping[str, object], pointer: str) -> str:
        value = self.member(parent, pointer)
        if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
            raise self.invalid(pointer, "sha256")
        return value

    def producer(self, parent: Mapping[str, object], pointer: str) -> str:
        value = self.member(parent, pointer)
        if not isinstance(value, str) or _PRODUCER.fullmatch(value) is None:
            raise self.invalid(pointer, "producer")
        return value

    def optional_text(
        self, parent: Mapping[str, object], pointer: str, rule: str
    ) -> str | None:
        """Return a text member that may be absent or null (None for both)."""
        value = parent.get(pointer.rsplit("/", 1)[-1])
        if value is None:
            return None
        if not isinstance(value, str) or not value or not _plain(value):
            raise self.invalid(pointer, rule)
        return value

    def area(self, value: object) -> AreaRef | None:
        if value is None:
            return None
        area = self.mapping(value, "/area")
        path = self.member(area, "/area/path")
        if not (
            isinstance(path, str)
            and path.startswith(f"{AREAS_DIR}/")
            and _relative(path)
        ):
            raise self.invalid("/area/path", "area_path")
        return AreaRef(path=path, sha256=self.sha256(area, "/area/sha256"))

    def stores(self, items: list[object]) -> dict[str, str]:
        stores: dict[str, str] = {}
        for index, item in enumerate(items):
            base = f"/stores/{index}"
            store = self.mapping(item, base)
            producer = self.producer(store, f"{base}/producer")
            if producer in stores:
                raise self.invalid(f"{base}/producer", "store_unique")
            root = self.member(store, f"{base}/root")
            if not isinstance(root, str) or not root or not _plain(root):
                raise self.invalid(f"{base}/root", "root")
            stores[producer] = root
        return stores

    def sets(self, items: list[object]) -> tuple[PinSet, ...]:
        sets: list[PinSet] = []
        taken: set[str] = set()
        for index, item in enumerate(items):
            base = f"/groups/{index}"
            group = self.mapping(item, base)
            name = self.name(group, f"{base}/name", "group_name", MAX_SET_NAME_CHARS)
            if "/" in name:
                raise self.invalid(f"{base}/name", "group_name")
            if name.casefold() in taken:
                raise self.invalid(f"{base}/name", "group_unique")
            taken.add(name.casefold())
            sets.append(self.pin_set(group, base, name))
        return tuple(sets)

    def pin_set(self, group: Mapping[str, object], base: str, name: str) -> PinSet:
        state = self.optional_text(group, f"{base}/state", "set_state")
        if state is not None and state not in _STATES:
            raise self.invalid(f"{base}/state", "set_state")
        closed_at = self.optional_text(group, f"{base}/closed_at", "time")
        if closed_at is not None and _TIME.fullmatch(closed_at) is None:
            raise self.invalid(f"{base}/closed_at", "time")
        closed_by = self.optional_text(group, f"{base}/closed_by", "account")
        digest = self.optional_text(group, f"{base}/pins_sha256", "sha256")
        if digest is not None and _SHA256.fullmatch(digest) is None:
            raise self.invalid(f"{base}/pins_sha256", "sha256")
        return PinSet(
            name=name,
            closed=state != "open",
            closed_at=closed_at,
            closed_by=closed_by,
            pins_sha256=digest,
            pins=self.pins(self.array(group, f"{base}/pins"), f"{base}/pins"),
        )

    def pins(self, items: list[object], base: str) -> tuple[Pin, ...]:
        pins: list[Pin] = []
        seen: set[tuple[str, str]] = set()
        for index, item in enumerate(items):
            pointer = f"{base}/{index}"
            pin = self.mapping(item, pointer)
            producer = self.producer(pin, f"{pointer}/producer")
            version = self.member(pin, f"{pointer}/version")
            if not isinstance(version, str) or not _relative(version):
                raise self.invalid(f"{pointer}/version", "version")
            if (producer, version) in seen:
                raise self.invalid(f"{pointer}/version", "pin_unique")
            seen.add((producer, version))
            size = self.member(pin, f"{pointer}/size_bytes")
            if not isinstance(size, int) or isinstance(size, bool) or size < 0:
                raise self.invalid(f"{pointer}/size_bytes", "size")
            pins.append(
                Pin(
                    producer=producer,
                    version=version,
                    sha256=self.sha256(pin, f"{pointer}/sha256"),
                    size_bytes=size,
                )
            )
        return tuple(pins)


def _plain(text: str) -> bool:
    """Whether a text holds no control character."""
    return not any(unicodedata.category(char) == "Cc" for char in text)


def _relative(path: str) -> bool:
    """Whether ``path`` is relative, ``/``-separated and without ``.`` or ``..``."""
    return (
        _plain(path)
        and "\\" not in path
        and not PureWindowsPath(path).anchor
        and all(part not in ("", ".", "..") for part in path.split("/"))
    )
