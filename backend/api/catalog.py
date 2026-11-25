"""Hydrograf's command catalog, ``hydrograf-commands/1`` (AGI §2, AGI-6.1, ADR-091).

Every operation of the API is one :class:`Command` here: its name ``<group> <verb>``,
the function that runs it, the model of its options, its domain document, its route
``/api/v1/<group>/<verb>``, its texts in English and Polish, its examples and the
registry codes it can answer. ``api.endpoints.commands`` serves each command at its
route from this table, the jobs of ``api.jobs`` run the long ones, and the commands
``commands list`` and ``commands schema`` answer the two documents of AGI-2.4:
:func:`command_list` (``hydrograf-command-list/1``, each entry with its ``rest``) and
:func:`command_schema` (``hydrograf-commands/1``).

Hydrograf is an ``app`` without a command line (ADR-091): ``function`` is the dotted
path of the Python function of the backend that runs the command, and the ``call`` of
an example is its HTTP call, the method and the path with its query and, for a POST,
the JSON body on the same line (for a long command, the start of its job). Every
command is read-only, uses no network and needs no key; a command's options are the
fields of its model, each with its JSON type, unit (from the suffix of its name,
DEV-8.2), bounds, default, enum with the meaning of each value, and description.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Final, Literal

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from api import API_BASE
from api.endpoints import (
    depressions,
    hydrograph,
    identify,
    layers,
    network,
    precipitation,
    profile,
    watershed,
)
from api.envelope import TOOL, Outcome
from core.errors import InvalidRequestError
from core.precipitation import DURATION_MIN_TO_STR, VALID_PROBABILITIES
from core.version import get_version
from models.schemas import (
    CommandsSchemaQuery,
    DelineateNetworkPreviewResponse,
    DelineateNetworkRequest,
    DelineateNetworkResponse,
    DelineatePreviewRequest,
    DelineatePreviewResponse,
    DelineateQuery,
    DelineateResponse,
    DepressionsQuery,
    DepressionsResponse,
    DesignDepthRequest,
    DesignDepthResponse,
    HydrographRequest,
    HydrographResponse,
    IdentifyPointRequest,
    IdentifyPointResponse,
    LayerAvailability,
    LayerThresholds,
    NoOptions,
    ScenariosResponse,
    TerrainProfileRequest,
    TerrainProfileResponse,
)

COMMANDS_SCHEMA: Final = f"{TOOL}-commands/1"
COMMAND_LIST_SCHEMA: Final = f"{TOOL}-command-list/1"

# Every command reads only: it changes nothing on the server and asks no provider
READ_ONLY: Final[Mapping[str, Any]] = {
    "read_only": True,
    "writes": "none",
    "idempotent": True,
    "network": False,
    "destructive": False,
}

# The unit of an option by the suffix of its name (DEV-8.2), the longest first, and
# of the options whose names carry none
_UNIT_SUFFIXES: Final = (
    ("_m3s", "m³/s"),
    ("_km2", "km²"),
    ("_m2", "m²"),
    ("_m3", "m³"),
    ("_percent", "%"),
    ("_min", "min"),
    ("_mm", "mm"),
    ("_km", "km"),
)
_UNITS: Final[Mapping[str, str]] = {
    "latitude": "°",
    "longitude": "°",
    "probability": "%",
    "min_volume": "m³",
    "max_volume": "m³",
    "min_area": "m²",
    "max_area": "m²",
}
# Codes every route can answer besides its own: the request limit and a defect
_EVERY_ROUTE: Final = ("rate_limited", "internal_error")


@dataclass(frozen=True)
class Example:
    """A call of a command and an excerpt of its answer."""

    call: str
    result: Mapping[str, Any]


@dataclass(frozen=True)
class Command:
    """One command of the catalog (AGI-2.2).

    Attributes
    ----------
    name : str
        ``<group> <verb>``.
    run : Callable[[Any, Session], Outcome]
        The function that runs it with its options and a database session.
    options : type[BaseModel]
        The model of its options: the query of a GET route, the body of a POST one.
    result : str
        The id of its domain document, ``hydrograf-<kind>/1``.
    document : type[BaseModel]
        The model of its domain document, for the OpenAPI document.
    method : {"GET", "POST"}
        GET for a command whose options a URL carries, POST for one with an object
        or a long array among them (AGI-6.1).
    summary, description : str
        One sentence starting with a verb; what it does, when to use it, when not
        and what instead, its main limit (English).
    rules : tuple of str
        Short imperative rules for agents.
    examples : tuple of Example
        At least one call with an excerpt of its answer.
    errors : tuple of str
        The registry codes its route answers besides ``rate_limited`` and
        ``internal_error``.
    summary_pl, description_pl : str
        The Polish texts.
    rules_pl : tuple of str
        The Polish rules.
    families : tuple of str
        ``core`` for the main commands (AGI-5.12), ``map`` for those of the map's
        panels, ``catalog`` for the catalog's own.
    cardinality : {"single", "bounded", "unbounded"}
        One document, or a bounded or unbounded collection.
    long : bool
        True for a run that can outlast a request: the command is served as a job
        only, its route answers ``409 conflict`` (``run_as_job``, AGI-6.10).
    meanings : Mapping[str, Mapping[Any, str]]
        The meaning of each value of an option whose values are listed (``enum``).
    """

    name: str
    run: Callable[[Any, Session], Outcome]
    options: type[BaseModel]
    result: str
    document: type[BaseModel]
    method: Literal["GET", "POST"]
    summary: str
    description: str
    rules: tuple[str, ...]
    examples: tuple[Example, ...]
    errors: tuple[str, ...]
    summary_pl: str
    description_pl: str
    rules_pl: tuple[str, ...]
    families: tuple[str, ...] = ("map",)
    cardinality: Literal["single", "bounded", "unbounded"] = "single"
    long: bool = False
    meanings: Mapping[str, Mapping[Any, str]] = field(default_factory=dict)

    @property
    def operation_id(self) -> str:
        """str: ``hydrograf_<group>_<verb>``, the OpenAPI ``operationId``."""
        return f"{TOOL}_{self.name.replace(' ', '_').replace('-', '_')}"

    @property
    def path(self) -> str:
        """str: The route, ``/api/v1/<group>/<verb>``."""
        return f"{API_BASE}/{self.name.replace(' ', '/')}"

    @property
    def function(self) -> str:
        """str: The dotted path of the function that runs the command."""
        return f"{self.run.__module__}.{self.run.__qualname__}"

    @property
    def rest(self) -> dict[str, Any]:
        """dict: The route as this server serves it: method, path, no key."""
        return {"method": self.method, "path": self.path, "key": False}

    @property
    def codes(self) -> tuple[str, ...]:
        """Tuple of str: Every registry code the route can answer."""
        return (*self.errors, *_EVERY_ROUTE)


class CommandList(BaseModel):
    """The summary of the catalog, ``hydrograf-command-list/1`` (AGI-2.4)."""

    tool: str = Field(TOOL, description="`hydrograf`")
    version: str = Field(..., description="The version of Hydrograf")
    commands: list[dict[str, Any]] = Field(
        ...,
        description="One entry per command: `name`, `operation_id`, `summary`, "
        "`read_only`, `effects`, `check`, `rest` (method, path and whether a run needs "
        "a key) and `long` for a command served as a job",
    )


class CommandCatalog(BaseModel):
    """The full catalog, ``hydrograf-commands/1`` (AGI §2)."""

    tool: str = Field(TOOL, description="`hydrograf`")
    version: str = Field(..., description="The version of Hydrograf")
    commands: list[dict[str, Any]] = Field(
        ..., description="The commands with their options, rules and examples"
    )


def list_commands(options: NoOptions, db: Session) -> Outcome:
    """Summarise the catalog: the command ``commands list``.

    Returns
    -------
    Outcome
        ``hydrograf-command-list/1`` without its ``schema``.
    """
    return Outcome(_without_schema(command_list()))


def describe_commands(options: CommandsSchemaQuery, db: Session) -> Outcome:
    """Describe one command or every command: the command ``commands schema``.

    Raises
    ------
    InvalidRequestError
        ``validation_error`` (400, ``unknown_command``) for a name of no command.
    """
    return Outcome(_without_schema(command_schema(options.command)))


def _without_schema(document: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in document.items() if key != "schema"}


def _duration_meanings() -> dict[int, str]:
    labels = {"min": " min", "h": " h"}
    meanings = {}
    for minutes, text in DURATION_MIN_TO_STR.items():
        unit = "min" if text.endswith("min") else "h"
        meanings[minutes] = f"{text.removesuffix(unit)}{labels[unit]} of rainfall"
    return meanings


def _probability_meanings() -> dict[float, str]:
    return {
        p: f"exceeded in a year with a probability of {p:g} % (return period "
        f"{100 / p:.4g} years)"
        for p in sorted(VALID_PROBABILITIES)
    }


_POINT_RULES: Final = ("Give latitude and longitude in WGS84 decimal degrees.",)
_POINT_RULES_PL: Final = ("Podaj latitude i longitude w stopniach dziesiętnych WGS84.",)
_JOB_RULE: Final = (
    'Run it as a job: POST /api/v1/jobs with {{"command": "{name}", "options": '
    "{{…}}}}, then follow jobs/<id> until it ends and read jobs/<id>/result."
)
_JOB_RULE_PL: Final = (
    'Uruchom jako zadanie: POST /api/v1/jobs z {{"command": "{name}", "options": '
    "{{…}}}}, śledź jobs/<id> do końca i odczytaj jobs/<id>/result."
)

COMMANDS: Final[tuple[Command, ...]] = (
    Command(
        name="watershed delineate",
        run=watershed.delineate_watershed,
        options=DelineateQuery,
        result="hydrograf-watershed/1",
        document=DelineateResponse,
        method="GET",
        families=("core",),
        summary="Delineate the watershed of a point in Poland and compute its "
        "parameters.",
        description=(
            "Delineates the watershed draining to the stream cell nearest the point on "
            "the server's precomputed flow network and returns its boundary as "
            "GeoJSON, outlet, area, morphometry, land cover and soil groups with the "
            "CN, the weights of the PMAXTP grid (`pmaxtp_grid`), the hand-off to "
            "Hydrolog (`handoff`, nogat-handoff/1) and the providers' lines. With "
            "`threshold_m2` it merges precomputed sub-catchments in seconds; without "
            "it the boundary is traced on the rasters from the exact point (precise "
            "mode, slower). When to use: first, before a hydrograph or a design depth; "
            "`result.watershed.boundary_geojson` feeds `precipitation depth`, "
            "`result.handoff.payload.nodes/0/watershed` Hydrolog's `hydrograph "
            "generate`. When not: for several outlets and tributaries use `network "
            "delineate`. Limit: only where the server's data lie (404 elsewhere); "
            "above 250 km² `hydrograph_available` is false."
        ),
        rules=(
            *_POINT_RULES,
            "Give threshold_m2, a value of `layers thresholds` (catchments), for the "
            "fast precomputed mode.",
            "Read snap_distance_m: an outlet over 500 m from the point comes with the "
            "notice outlet_far_from_point.",
        ),
        examples=(
            Example(
                "GET /api/v1/watershed/delineate?latitude=51.01917&longitude=15.88497"
                "&threshold_m2=100000",
                {
                    "status": "ok",
                    "result": {
                        "schema": "hydrograf-watershed/1",
                        "mode": "precomputed",
                        "watershed": {
                            "area_km2": 149.78,
                            "hydrograph_available": True,
                            "morphometry": {"area_km2": 149.7772, "cn": 61.7},
                        },
                    },
                    "notices": [],
                },
            ),
        ),
        errors=(
            "validation_error",
            "not_found",
            "unsupported",
            "calculation_error",
            "store_unavailable",
        ),
        summary_pl="Wyznacz zlewnię punktu w Polsce i oblicz jej parametry.",
        description_pl=(
            "Wyznacza zlewnię odcinka cieku najbliższego punktowi na przeliczonej "
            "sieci spływu serwera i zwraca jej granicę w GeoJSON, ujście, "
            "powierzchnię, parametry morfometryczne, pokrycie terenu i grupy glebowe z "
            "CN, wagi siatki PMAXTP (`pmaxtp_grid`), przekazanie do Hydrologa "
            "(`handoff`) i linie dostawców danych. Z `threshold_m2` łączy przeliczone "
            "zlewnie elementarne w kilka sekund; bez niego granica jest wyznaczana na "
            "rastrach od dokładnego punktu (tryb dokładny, wolniejszy). Kiedy: "
            "najpierw, przed hydrogramem lub opadem miarodajnym. Kiedy nie: dla wielu "
            "przekrojów użyj `network delineate`. Limit: tylko w obszarze danych "
            "serwera; powyżej 250 km² `hydrograph_available` jest false."
        ),
        rules_pl=(
            *_POINT_RULES_PL,
            "Podaj threshold_m2 z `layers thresholds` (catchments) dla szybkiego "
            "trybu.",
            "Sprawdź snap_distance_m: ujście dalej niż 500 m od punktu ma "
            "komunikat outlet_far_from_point.",
        ),
    ),
    Command(
        name="watershed preview",
        run=watershed.preview_watershed,
        options=DelineatePreviewRequest,
        result="hydrograf-watershed-preview/1",
        document=DelineatePreviewResponse,
        method="GET",
        cardinality="bounded",
        summary="List the sub-catchments a precomputed delineation of a point merges, "
        "by their depth from the outlet.",
        description=(
            "Answers in a fraction of a second, before `watershed delineate` with the "
            "same latitude, longitude and threshold_m2 ends: the threshold of the "
            "merge after the cascade, the number of sub-catchments and their "
            "simplified outlines grouped by breadth-first depth from the outlet "
            "(GeoJSON, WGS84, at most 5000). When to use: to show the progress of a "
            "delineation. When not: it gives no boundary, area or parameters, use "
            "`watershed delineate`; the precise mode has no preview."
        ),
        rules=(
            *_POINT_RULES,
            "Give the latitude, longitude and threshold_m2 of the delineation it "
            "previews.",
        ),
        examples=(
            Example(
                "GET /api/v1/watershed/preview?latitude=51.01917&longitude=15.88497"
                "&threshold_m2=100000",
                {
                    "status": "ok",
                    "result": {
                        "schema": "hydrograf-watershed-preview/1",
                        "threshold_m2": 100000,
                        "catchments": {"type": "FeatureCollection"},
                    },
                },
            ),
        ),
        errors=("validation_error", "not_found", "store_unavailable"),
        summary_pl="Wypisz zlewnie elementarne łączone przy wyznaczaniu zlewni punktu, "
        "według ich odległości od ujścia.",
        description_pl=(
            "Odpowiada w ułamku sekundy, zanim skończy się `watershed delineate` z "
            "tymi samymi latitude, longitude i threshold_m2: próg łączenia, liczbę "
            "zlewni elementarnych i ich uproszczone obrysy według głębokości od ujścia "
            "(GeoJSON, WGS84). Kiedy: do pokazania postępu wyznaczania. Kiedy nie: nie "
            "daje granicy ani parametrów, użyj `watershed delineate`."
        ),
        rules_pl=(
            *_POINT_RULES_PL,
            "Podaj latitude, longitude i threshold_m2 wyznaczania, które poprzedza.",
        ),
    ),
    Command(
        name="network delineate",
        run=network.delineate_network,
        options=DelineateNetworkRequest,
        result="hydrograf-network/1",
        document=DelineateNetworkResponse,
        method="POST",
        long=True,
        families=("core",),
        summary="Delineate a network of subcatchments, reaches and junctions above a "
        "closing section and control points.",
        description=(
            "Snaps the closing section (`outlet`) and up to 30 points above it "
            "(tributaries, gauges) to the stream network of `threshold_m2`, splits "
            "the closing section's catchment into headwater and intermediate "
            "subcatchments joined by reaches, and returns each subcatchment with the "
            "parameters of a delineated watershed, each reach with its length and "
            "slope, the junctions, the boundary, the check of the areas and the "
            "hand-off of the network to Hydrolog (nogat-handoff/1 with "
            "hydrolog-network/1). Served as a job only: it can outlast a request. "
            "When to use: a catchment with gauges or tributaries to route. When not: "
            "while placing the points use `network preview`; for one outlet use "
            "`watershed delineate`."
        ),
        rules=(
            _JOB_RULE.format(name="network delineate"),
            "Give each point an id unique in the request: letters, digits, _ and -, "
            "at most 16 characters.",
            "threshold_m2 is at least 10000.",
        ),
        examples=(
            Example(
                'POST /api/v1/jobs {"command": "network delineate", "options": '
                '{"outlet": {"id": "out", "latitude": 51.01917, "longitude": '
                '15.88497}, "points": [{"id": "g1", "latitude": 51.03, "longitude": '
                '15.9}], "threshold_m2": 100000}}',
                {
                    "status": "ok",
                    "result": {
                        "schema": "hydrograf-network/1",
                        "subcatchments": [{"id": "Z1", "kind": "headwater"}],
                        "reaches": [{"id": "R1", "from": "P1", "to": "P0"}],
                    },
                },
            ),
        ),
        errors=(
            "validation_error",
            "not_found",
            "unsupported",
            "calculation_error",
            "store_unavailable",
            "conflict",
        ),
        summary_pl="Wyznacz sieć zlewni cząstkowych, odcinków i węzłów powyżej "
        "przekroju zamykającego i punktów kontrolnych.",
        description_pl=(
            "Dowiązuje przekrój zamykający (`outlet`) i do 30 punktów powyżej niego "
            "(dopływy, wodowskazy) do sieci cieków progu `threshold_m2`, dzieli "
            "zlewnię "
            "przekroju na zlewnie źródłowe i przyrzecza połączone odcinkami i zwraca "
            "każdą zlewnię z parametrami jak dla wyznaczonej zlewni, każdy odcinek z "
            "długością i spadkiem, węzły, granicę, kontrolę powierzchni i przekazanie "
            "sieci do Hydrologa. Tylko jako zadanie: może trwać dłużej niż żądanie. "
            "Kiedy nie: przy rozmieszczaniu punktów użyj `network preview`, dla "
            "jednego ujścia `watershed delineate`."
        ),
        rules_pl=(
            _JOB_RULE_PL.format(name="network delineate"),
            "Nadaj każdemu punktowi id unikalne w żądaniu: litery, cyfry, _ i -, do "
            "16 znaków.",
            "threshold_m2 wynosi co najmniej 10000.",
        ),
    ),
    Command(
        name="network preview",
        run=network.preview_network,
        options=DelineateNetworkRequest,
        result="hydrograf-network-preview/1",
        document=DelineateNetworkPreviewResponse,
        method="POST",
        summary="Preview the network of a closing section and control points: where "
        "they snap, the tree and the outlines.",
        description=(
            "The same request as `network delineate`, answered in a fraction of a "
            "second on the catchment graph: where each point snaps and its node, the "
            "tree of subcatchments with the area of each element and the length of "
            "each reach, and their outlines (GeoJSON); no parameters and no hand-off. "
            "When to use: while placing the points. When not: for the parameters and "
            "the hand-off use `network delineate`."
        ),
        rules=(
            "Send the body `network delineate` takes.",
            "Give each point an id unique in the request.",
        ),
        examples=(
            Example(
                'POST /api/v1/network/preview {"outlet": {"id": "out", "latitude": '
                '51.01917, "longitude": 15.88497}, "points": [], "threshold_m2": '
                "100000}",
                {
                    "status": "ok",
                    "result": {
                        "schema": "hydrograf-network-preview/1",
                        "subcatchments": [{"id": "Z1", "kind": "headwater"}],
                    },
                },
            ),
        ),
        # No window of the closing section's catchment is read: no 422 for a large one
        errors=("validation_error", "not_found", "store_unavailable"),
        summary_pl="Podejrzyj sieć przekroju zamykającego i punktów kontrolnych: "
        "dowiązanie, drzewo i obrysy.",
        description_pl=(
            "To samo żądanie co `network delineate`, z odpowiedzią w ułamku sekundy: "
            "gdzie dowiązuje się każdy punkt i jego węzeł, drzewo zlewni z "
            "powierzchnią każdego elementu i długością każdego odcinka oraz ich obrysy "
            "(GeoJSON); bez parametrów i przekazania. Kiedy: przy rozmieszczaniu "
            "punktów."
        ),
        rules_pl=(
            "Wyślij treść, którą przyjmuje `network delineate`.",
            "Nadaj każdemu punktowi id unikalne w żądaniu.",
        ),
    ),
    Command(
        name="hydrograph generate",
        run=hydrograph.generate_hydrograph,
        options=HydrographRequest,
        result="hydrograf-hydrograph/1",
        document=HydrographResponse,
        method="POST",
        long=True,
        families=("core",),
        meanings={
            "uh_model": {
                "scs": "the SCS dimensionless unit hydrograph (NRCS)",
                "snyder": "Snyder's synthetic unit hydrograph (Ct, Cp)",
                "nash": "Nash's cascade of linear reservoirs (n, K)",
            },
            "nash_estimation": {
                "from_lutz": "n and K by Lutz's regression (forest, urban land, "
                "channel)",
                "from_urban_regression": "n and K by the urban regression of the "
                "effective rainfall and its duration",
            },
            "amc": {
                "I": "dry antecedent moisture: the CN lowered",
                "II": "average antecedent moisture: the CN as tabulated",
                "III": "wet antecedent moisture: the CN raised",
            },
        },
        summary="Generate the design hydrograph of a watershed in Poland from PMAXTP "
        "rainfall or an own series.",
        description=(
            "Computes the direct-runoff hydrograph at the outlet of a point's "
            "watershed: the watershed is delineated as `watershed delineate` does, or "
            "taken from `morphometry` with its `pmaxtp_grid`; the design depth is its "
            "PMAXTP mean for `duration` and `probability` (the depth of `precipitation "
            "depth`), distributed by the hyetograph; the effective rainfall by SCS-CN "
            "with the AMC, the time of concentration by `tc_method` and the unit "
            "hydrograph by `uh_model`, all with Hydrolog. Returns the rainfall, the "
            "hydrograph, the water balance, Hydrolog's warnings as notices and the "
            "hand-off with the result. Served as a job only: a large catchment takes "
            "minutes. When not: for the depth alone use `precipitation depth`. "
            "Limit: catchments up to 250 km² (SCS-CN; 422 above)."
        ),
        rules=(
            _JOB_RULE.format(name="hydrograph generate"),
            "Give duration and probability, values of `hydrograph scenarios`, or "
            "custom_precipitation.",
            "Give tc_runoff_coeff with tc_method faa, tc_retardance with kerby or "
            "kerby_kirpich.",
        ),
        examples=(
            Example(
                'POST /api/v1/jobs {"command": "hydrograph generate", "options": '
                '{"latitude": 51.01917, "longitude": 15.88497, "duration": "1h", '
                '"probability": 1}}',
                {
                    "status": "ok",
                    "result": {
                        "schema": "hydrograf-hydrograph/1",
                        "precipitation": {"source": "pmaxtp", "duration_min": 60.0},
                        "hydrograph": {
                            "peak_discharge_m3s": 7.866,
                            "time_to_peak_min": 310.0,
                        },
                    },
                    "notices": [],
                },
            ),
        ),
        errors=(
            "validation_error",
            "not_found",
            "no_data",
            "unsupported",
            "calculation_error",
            "store_unavailable",
            "conflict",
        ),
        summary_pl="Wygeneruj hydrogram projektowy zlewni w Polsce z opadu PMAXTP lub "
        "własnego szeregu.",
        description_pl=(
            "Oblicza hydrogram odpływu bezpośredniego w ujściu zlewni punktu: zlewnia "
            "jest wyznaczana jak w `watershed delineate` albo brana z `morphometry` z "
            "jej `pmaxtp_grid`; opad miarodajny to średnia PMAXTP zlewni dla "
            "`duration` i `probability` (ten sam co z `precipitation depth`), "
            "rozłożona hietogramem; opad efektywny metodą SCS-CN z AMC, czas "
            "koncentracji metodą `tc_method`, hydrogram jednostkowy modelem "
            "`uh_model`, wszystko w Hydrologu. Tylko jako zadanie: duża zlewnia liczy "
            "się minuty. Kiedy nie: dla samego opadu użyj `precipitation depth`. "
            "Limit: zlewnie do 250 km² (SCS-CN)."
        ),
        rules_pl=(
            _JOB_RULE_PL.format(name="hydrograph generate"),
            "Podaj duration i probability z `hydrograph scenarios` albo "
            "custom_precipitation.",
            "Podaj tc_runoff_coeff dla metody faa, tc_retardance dla kerby i "
            "kerby_kirpich.",
        ),
    ),
    Command(
        name="hydrograph scenarios",
        run=hydrograph.list_scenarios,
        options=NoOptions,
        result="hydrograf-scenarios/1",
        document=ScenariosResponse,
        method="GET",
        families=("core",),
        summary="List the rainfall durations, probabilities, methods and limits that "
        "`hydrograph generate` accepts.",
        description=(
            "The PMAXTP durations and exceedance probabilities, the methods of the "
            "time of concentration, the hyetographs, the unit hydrographs and Nash's "
            "estimations, the AMC classes, Snyder's default coefficients, the most "
            "steps of an own series and the area limit. When to use: to fill a form "
            "or check values before `hydrograph generate`. When not: it computes "
            "nothing."
        ),
        rules=("Take duration and probability of a hydrograph from these lists.",),
        examples=(
            Example(
                "GET /api/v1/hydrograph/scenarios",
                {
                    "status": "ok",
                    "result": {
                        "schema": "hydrograf-scenarios/1",
                        "durations": ["5min", "10min", "15min"],
                        "area_limit_km2": 250.0,
                    },
                },
            ),
        ),
        errors=(),
        summary_pl="Wypisz czasy trwania i prawdopodobieństwa opadu, metody i limity, "
        "które przyjmuje `hydrograph generate`.",
        description_pl=(
            "Czasy trwania i prawdopodobieństwa przewyższenia PMAXTP, metody czasu "
            "koncentracji, hietogramy, hydrogramy jednostkowe i estymacje Nasha, klasy "
            "AMC, domyślne współczynniki Snydera, największą liczbę kroków własnego "
            "szeregu i limit powierzchni. Kiedy: do wypełnienia formularza. Niczego "
            "nie oblicza."
        ),
        rules_pl=("Bierz duration i probability hydrogramu z tych list.",),
    ),
    Command(
        name="precipitation depth",
        run=precipitation.design_depth,
        options=DesignDepthRequest,
        result="hydrograf-design-depth/1",
        document=DesignDepthResponse,
        method="POST",
        families=("core",),
        meanings={
            "duration_min": _duration_meanings(),
            "probability_percent": _probability_meanings(),
        },
        summary="Compute a catchment's PMAXTP design depth for a duration and a "
        "probability.",
        description=(
            "The mean over the catchment of the PMAXTP depths of the server's grid, "
            "each grid point weighted by the area of its Thiessen polygon inside the "
            "boundary (the method of the Polish methodology for design floods), with "
            "each point's depth and weight and PMAXTP's lines. It is the depth "
            "`hydrograph generate` takes, unrounded and without an areal reduction "
            "factor. When to use: with `result.watershed.boundary_geojson` of "
            "`watershed delineate`, before a hydrograph computed elsewhere. When not: "
            "for a point without a boundary use Obserwator's `pmaxtp fetch`. Limit: "
            "10 000 km²."
        ),
        rules=(
            "Send boundary as a GeoJSON Polygon or MultiPolygon, or a Feature of one, "
            "in WGS84.",
            "duration_min and probability_percent are values of PMAXTP's tables.",
        ),
        examples=(
            Example(
                'POST /api/v1/precipitation/depth {"boundary": {"type": "Polygon", '
                '"coordinates": [[[15.85, 51.0], [15.95, 51.0], [15.95, 51.06], '
                '[15.85, 51.06], [15.85, 51.0]]]}, "duration_min": 60, '
                '"probability_percent": 1}',
                {
                    "status": "ok",
                    "result": {
                        "schema": "hydrograf-design-depth/1",
                        "duration_min": 60,
                        "probability_percent": 1,
                        "interpolation": "thiessen",
                    },
                },
            ),
        ),
        errors=("validation_error", "no_data", "unsupported"),
        summary_pl="Oblicz opad miarodajny PMAXTP zlewni dla czasu trwania i "
        "prawdopodobieństwa.",
        description_pl=(
            "Średnia z wysokości opadu PMAXTP siatki serwera po zlewni, z wagą punktu "
            "równą powierzchni jego wieloboku Thiessena w granicy (metoda polskiej "
            "metodyki obliczania przepływów miarodajnych), z wysokością i wagą każdego "
            "punktu oraz liniami PMAXTP. To ten sam opad, który bierze `hydrograph "
            "generate`, bez zaokrąglenia i bez współczynnika redukcji obszarowej. "
            "Kiedy: z granicą z `watershed delineate`. Kiedy nie: dla punktu bez "
            "granicy użyj `pmaxtp fetch` Obserwatora. Limit: 10 000 km²."
        ),
        rules_pl=(
            "Wyślij boundary jako Polygon lub MultiPolygon GeoJSON albo Feature z nim, "
            "w WGS84.",
            "duration_min i probability_percent to wartości z tabel PMAXTP.",
        ),
    ),
    Command(
        name="terrain profile",
        run=profile.terrain_profile,
        options=TerrainProfileRequest,
        result="hydrograf-terrain-profile/1",
        document=TerrainProfileResponse,
        method="POST",
        summary="Sample the terrain elevation, and the water levels of analysis "
        "results, along a line.",
        description=(
            "Samples the server's NMT at n_samples points spaced evenly along a "
            "GeoJSON LineString (WGS84) and returns the distances, elevations, the "
            "samples without DEM data, the total length and, for the requested "
            "analysis results, their maximum water levels, with the NMT's lines. When "
            "to use: a cross-section or a longitudinal profile. When not: for a "
            "watershed's parameters use `watershed delineate`."
        ),
        rules=(
            "Send geometry as a GeoJSON LineString of at least two points in WGS84.",
        ),
        examples=(
            Example(
                'POST /api/v1/terrain/profile {"geometry": {"type": "LineString", '
                '"coordinates": [[15.88, 51.01], [15.9, 51.02]]}, "n_samples": 100}',
                {
                    "status": "ok",
                    "result": {
                        "schema": "hydrograf-terrain-profile/1",
                        "water_levels": [],
                    },
                },
            ),
        ),
        errors=("validation_error", "no_data", "store_unavailable"),
        summary_pl="Odczytaj wysokość terenu i poziomy wody wyników analiz wzdłuż "
        "linii.",
        description_pl=(
            "Próbkuje NMT serwera w n_samples punktach równomiernie wzdłuż linii "
            "GeoJSON (WGS84) i zwraca odległości, wysokości, próbki bez danych NMT, "
            "długość i maksymalne poziomy wody wybranych wyników analiz, z liniami "
            "NMT. Kiedy: przekrój poprzeczny lub podłużny. Kiedy nie: dla parametrów "
            "zlewni użyj `watershed delineate`."
        ),
        rules_pl=(
            "Wyślij geometry jako LineString GeoJSON z co najmniej dwóch punktów.",
        ),
    ),
    Command(
        name="point identify",
        run=identify.identify_point,
        options=IdentifyPointRequest,
        result="hydrograf-point/1",
        document=IdentifyPointResponse,
        method="GET",
        summary="Report what Hydrograf knows at a point: coordinates, terrain, water, "
        "land cover and sub-catchment.",
        description=(
            "For a point (WGS84): its coordinates in WGS84, PL-1992 and PL-2000, the "
            "NMT's elevation and slope, the water of the requested analysis results, "
            "the nearest BDOT10k stream within 5 km and the water body containing the "
            "point, the land cover, the soil group, the depression and the "
            "precomputed sub-catchment of `threshold_m2` with its main channel; a "
            "member is null where its source has nothing. When to use: to inspect a "
            "place on the map. When not: for a watershed use `watershed delineate`. "
            "Limit: a point off the NMT answers 404 no_data."
        ),
        rules=(
            *_POINT_RULES,
            "Repeat result_ids for each analysis result: ?result_ids=a&result_ids=b.",
        ),
        examples=(
            Example(
                "GET /api/v1/point/identify?latitude=51.0376&longitude=16.1723"
                "&threshold_m2=100000",
                {
                    "status": "ok",
                    "result": {
                        "schema": "hydrograf-point/1",
                        "coordinates": {"latitude": 51.0376, "longitude": 16.1723},
                    },
                },
            ),
        ),
        errors=("validation_error", "no_data", "store_unavailable"),
        summary_pl="Podaj, co Hydrograf wie o punkcie: współrzędne, teren, wodę, "
        "pokrycie terenu i zlewnię elementarną.",
        description_pl=(
            "Dla punktu (WGS84): współrzędne w WGS84, PL-1992 i PL-2000, wysokość i "
            "spadek NMT, woda wybranych wyników analiz, najbliższy ciek BDOT10k do 5 "
            "km i zbiornik wodny, pokrycie terenu, grupa glebowa, zagłębienie i "
            "zlewnia elementarna progu `threshold_m2` z ciekiem głównym; null tam, "
            "gdzie źródło nic nie ma. Kiedy nie: dla zlewni użyj `watershed "
            "delineate`."
        ),
        rules_pl=(
            *_POINT_RULES_PL,
            "Powtórz result_ids dla każdego wyniku: ?result_ids=a&result_ids=b.",
        ),
    ),
    Command(
        name="depressions list",
        run=depressions.list_depressions,
        options=DepressionsQuery,
        result="hydrograf-depressions/1",
        document=DepressionsResponse,
        method="GET",
        cardinality="bounded",
        summary="List the terrain depressions by volume and area, optionally within a "
        "bounding box.",
        description=(
            "The depressions of the NMT (blue spots) the preprocessing found, filtered "
            "by volume and area and optionally by a bounding box (WGS84), as a GeoJSON "
            "FeatureCollection of at most 500 polygons, the largest volume first, each "
            "with its volume, area and depths. When to use: to find where water ponds. "
            "When not: it is no flood model."
        ),
        rules=("Give bbox as minlon,minlat,maxlon,maxlat in WGS84.",),
        examples=(
            Example(
                "GET /api/v1/depressions/list?min_volume=100&bbox=16.9,52.3,17.4,52.6",
                {
                    "status": "ok",
                    "result": {
                        "schema": "hydrograf-depressions/1",
                        "type": "FeatureCollection",
                    },
                },
            ),
        ),
        errors=("validation_error",),
        summary_pl="Wypisz zagłębienia terenu według objętości i powierzchni, "
        "opcjonalnie w prostokącie.",
        description_pl=(
            "Zagłębienia NMT znalezione przy przetwarzaniu, filtrowane objętością i "
            "powierzchnią, opcjonalnie prostokątem (WGS84), jako FeatureCollection "
            "GeoJSON do 500 wieloboków, od największej objętości. Kiedy nie: to nie "
            "jest model powodziowy."
        ),
        rules_pl=("Podaj bbox jako minlon,minlat,maxlon,maxlat w WGS84.",),
    ),
    Command(
        name="layers availability",
        run=layers.layer_availability,
        options=NoOptions,
        result="hydrograf-layers/1",
        document=LayerAvailability,
        method="GET",
        summary="Report which optional map layers hold data on this server.",
        description=(
            "`sewer` is true when the server holds a sewer network. When to use: to "
            "hide the layers whose tiles would be empty. It computes nothing."
        ),
        rules=("Hide a layer whose member is false.",),
        examples=(
            Example(
                "GET /api/v1/layers/availability",
                {
                    "status": "ok",
                    "result": {"schema": "hydrograf-layers/1", "sewer": False},
                },
            ),
        ),
        errors=(),
        summary_pl="Podaj, które opcjonalne warstwy mapy mają dane na tym serwerze.",
        description_pl=(
            "`sewer` jest true, gdy serwer ma sieć kanalizacji. Kiedy: do ukrycia "
            "warstw, których kafle byłyby puste."
        ),
        rules_pl=("Ukryj warstwę, której pole jest false.",),
    ),
    Command(
        name="layers thresholds",
        run=layers.layer_thresholds,
        options=NoOptions,
        result="hydrograf-thresholds/1",
        document=LayerThresholds,
        method="GET",
        summary="List the flow accumulation thresholds of the stream network and of "
        "the sub-catchments.",
        description=(
            "The thresholds [m²] at which the preprocessing built the stream network "
            "(`streams`) and the sub-catchments (`catchments`). When to use: to choose "
            "the threshold_m2 of a delineation, one of `catchments`. It computes "
            "nothing."
        ),
        rules=("Take threshold_m2 of a delineation from catchments.",),
        examples=(
            Example(
                "GET /api/v1/layers/thresholds",
                {
                    "status": "ok",
                    "result": {
                        "schema": "hydrograf-thresholds/1",
                        "streams": [10000, 100000, 1000000, 10000000],
                        "catchments": [10000, 100000, 1000000, 10000000],
                    },
                },
            ),
        ),
        errors=(),
        summary_pl="Wypisz progi akumulacji spływu sieci cieków i zlewni "
        "elementarnych.",
        description_pl=(
            "Progi [m²], dla których przetwarzanie zbudowało sieć cieków (`streams`) i "
            "zlewnie elementarne (`catchments`). Kiedy: do wyboru threshold_m2 "
            "wyznaczania, jednego z `catchments`."
        ),
        rules_pl=("Bierz threshold_m2 wyznaczania z catchments.",),
    ),
    Command(
        name="commands list",
        run=list_commands,
        options=NoOptions,
        result=COMMAND_LIST_SCHEMA,
        document=CommandList,
        method="GET",
        families=("core", "catalog"),
        cardinality="bounded",
        summary="List Hydrograf's commands with their routes and effects.",
        description=(
            "One entry per command: its name, operation id, one-sentence summary, "
            "effects, whether it reads only and its route on this server (`rest`: "
            "method, path and whether a run needs a key), and `long` for a command "
            "served as a job. When to use: first, to discover the commands. When not: "
            "for options, rules and examples use `commands schema`."
        ),
        rules=("Start discovery here, then ask commands schema for one command.",),
        examples=(
            Example(
                "GET /api/v1/commands/list",
                {
                    "status": "ok",
                    "result": {
                        "schema": "hydrograf-command-list/1",
                        "commands": [
                            {
                                "name": "watershed delineate",
                                "rest": {
                                    "method": "GET",
                                    "path": "/api/v1/watershed/delineate",
                                    "key": False,
                                },
                            }
                        ],
                    },
                },
            ),
        ),
        errors=(),
        summary_pl="Wypisz polecenia Hydrografu z ich trasami i skutkami.",
        description_pl=(
            "Jeden wpis na polecenie: nazwa, identyfikator operacji, streszczenie, "
            "skutki, czy tylko odczytuje i trasa na tym serwerze (`rest`), oraz `long` "
            "dla polecenia uruchamianego jako zadanie. Kiedy: najpierw. Kiedy nie: "
            "opcje, reguły i przykłady daje `commands schema`."
        ),
        rules_pl=("Zacznij tutaj, potem zapytaj commands schema o jedno polecenie.",),
    ),
    Command(
        name="commands schema",
        run=describe_commands,
        options=CommandsSchemaQuery,
        result=COMMANDS_SCHEMA,
        document=CommandCatalog,
        method="GET",
        families=("core", "catalog"),
        cardinality="bounded",
        summary="Describe one command, or every command, with its options, rules, "
        "examples and errors.",
        description=(
            "The full catalog hydrograf-commands/1, or the entry of `command` alone: "
            "the options with their types, units, bounds and defaults, the result "
            "document, effects, route, rules, examples and registry error codes, with "
            "Polish texts. When to use: after `commands list`, before calling a "
            "command. When not: to list the commands use `commands list`."
        ),
        rules=("Give command as <group> <verb>, e.g. watershed delineate.",),
        examples=(
            Example(
                "GET /api/v1/commands/schema?command=precipitation%20depth",
                {
                    "status": "ok",
                    "result": {
                        "schema": "hydrograf-commands/1",
                        "commands": [
                            {
                                "name": "precipitation depth",
                                "operation_id": "hydrograf_precipitation_depth",
                            }
                        ],
                    },
                },
            ),
        ),
        errors=("validation_error",),
        summary_pl="Opisz jedno polecenie albo wszystkie: opcje, reguły, przykłady i "
        "błędy.",
        description_pl=(
            "Pełny katalog hydrograf-commands/1 albo wpis polecenia `command`: opcje z "
            "typami, jednostkami, zakresami i wartościami domyślnymi, dokument wyniku, "
            "skutki, trasa, reguły, przykłady i kody błędów. Kiedy: po `commands "
            "list`, przed wywołaniem polecenia."
        ),
        rules_pl=("Podaj command jako <grupa> <czasownik>, np. watershed delineate.",),
    ),
)

BY_NAME: Final[Mapping[str, Command]] = {command.name: command for command in COMMANDS}
LONG: Final[tuple[str, ...]] = tuple(c.name for c in COMMANDS if c.long)


def find(name: str) -> Command:
    """Return the command named ``name``.

    Raises
    ------
    InvalidRequestError
        ``validation_error`` (400, ``unknown_command``) for a name of no command.
    """
    command = BY_NAME.get(name)
    if command is None:
        raise InvalidRequestError(
            "unknown_command",
            reason="unknown_command",
            option="command",
            command=name,
            allowed=sorted(BY_NAME),
        )
    return command


def _unit(name: str) -> str | None:
    if name in _UNITS:
        return _UNITS[name]
    for suffix, unit in _UNIT_SUFFIXES:
        if name.endswith(suffix):
            return unit
    return None


def _without_null(prop: Mapping[str, Any]) -> Mapping[str, Any]:
    """Return the schema of an optional field without its ``null`` alternative."""
    alternatives = prop.get("anyOf")
    if not alternatives:
        return prop
    kept = [item for item in alternatives if item.get("type") != "null"]
    return kept[0] if len(kept) == 1 else prop


def _json_type(prop: Mapping[str, Any]) -> str:
    if "$ref" in prop:
        return "object"
    kind = prop.get("type")
    if isinstance(kind, str):
        return kind
    values = prop.get("enum")
    if values:
        if all(isinstance(v, bool) for v in values):
            return "boolean"
        if all(isinstance(v, int) for v in values):
            return "integer"
        if all(isinstance(v, int | float) for v in values):
            return "number"
        return "string"
    return "object"


def _items(prop: Mapping[str, Any]) -> str | dict[str, Any]:
    items = _without_null(prop.get("items", {}))
    kind = _json_type(items)
    plain = set(items) <= {"type", "title"}
    return kind if "$ref" in items or plain else dict(items)


def _option(
    name: str,
    raw: Mapping[str, Any],
    required: bool,
    meanings: Mapping[Any, str] | None,
) -> dict[str, Any]:
    """Return one option of the catalog from the JSON Schema of its field (AGI-2.3)."""
    prop = _without_null(raw)
    kind = _json_type(prop)
    entry: dict[str, Any] = {
        "name": name,
        "type": kind,
        "required": required,
        "description": raw.get("description") or prop.get("description") or "",
    }
    unit = _unit(name)
    if unit is not None:
        entry["unit"] = unit
    if not required and raw.get("default") is not None:
        entry["default"] = raw["default"]
    values = prop.get("enum")
    if values:
        if meanings is None:
            raise ValueError(f"option {name!r} lists values without their meanings")
        entry["enum"] = [
            {"value": value, "meaning": meanings[value]} for value in values
        ]
    for key, member in (
        ("minimum", "min"),
        ("maximum", "max"),
        ("exclusiveMinimum", "exclusive_minimum"),
        ("exclusiveMaximum", "exclusive_maximum"),
        ("pattern", "pattern"),
    ):
        if key in prop:
            entry[member] = prop[key]
    if kind == "array":
        entry["items"] = _items(prop)
    examples = raw.get("examples") or prop.get("examples")
    if examples:
        entry["examples"] = list(examples)
    return entry


def options_of(command: Command) -> list[dict[str, Any]]:
    """Return the options of ``command``, the fields of its model in their order."""
    schema = command.options.model_json_schema()
    required = set(schema.get("required", ()))
    return [
        _option(name, prop, name in required, command.meanings.get(name))
        for name, prop in schema.get("properties", {}).items()
    ]


def entry(command: Command) -> dict[str, Any]:
    """Return the entry of ``command`` in ``hydrograf-commands/1`` (AGI-2.2)."""
    document: dict[str, Any] = {
        "name": command.name,
        "operation_id": command.operation_id,
        "function": command.function,
        "summary": command.summary,
        "description": command.description,
        "options": options_of(command),
        "result": {"schema": command.result, "cardinality": command.cardinality},
        "effects": dict(READ_ONLY),
        "check": None,
        "rest": command.rest,
    }
    if command.long:
        document["long"] = True
    document.update(
        {
            "families": list(command.families),
            "rules": list(command.rules),
            "examples": [
                {"call": example.call, "result": dict(example.result)}
                for example in command.examples
            ],
            "errors": list(command.codes),
            "i18n": {
                "pl": {
                    "summary": command.summary_pl,
                    "description": command.description_pl,
                    "rules": list(command.rules_pl),
                }
            },
        }
    )
    return document


def command_schema(name: str | None = None) -> dict[str, Any]:
    """Return the catalog ``hydrograf-commands/1``, whole or of one command.

    Raises
    ------
    InvalidRequestError
        ``validation_error`` (400, ``unknown_command``) for a name of no command.
    """
    chosen = COMMANDS if name is None else (find(name),)
    return {
        "schema": COMMANDS_SCHEMA,
        "tool": TOOL,
        "version": get_version(),
        "commands": [entry(command) for command in chosen],
    }


def command_list() -> dict[str, Any]:
    """Return the summary ``hydrograf-command-list/1``, each entry with its ``rest``."""
    rows = []
    for command in COMMANDS:
        row: dict[str, Any] = {
            "name": command.name,
            "operation_id": command.operation_id,
            "summary": command.summary,
            "read_only": READ_ONLY["read_only"],
            "effects": dict(READ_ONLY),
            "check": None,
            "rest": command.rest,
        }
        if command.long:
            row["long"] = True
        rows.append(row)
    return {
        "schema": COMMAND_LIST_SCHEMA,
        "tool": TOOL,
        "version": get_version(),
        "commands": rows,
    }
