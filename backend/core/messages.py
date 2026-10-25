"""Message catalogue of the errors of the REST API (DEV-2.3, ERR-6, AGI-6.4).

Code refers to a message by its English ID. Each message has an English text, which
answers requests without ``Accept-Language``, and a Polish text for
``Accept-Language: pl`` (the interface sends it). A text may use ``{name}`` fields,
which the details of the error fill in; a message may also carry a hint, the one line
that tells how to fix the call (ERR-5). Codes, ``details`` keys and reasons do not
depend on the language.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final, Literal

type Language = Literal["en", "pl"]


@dataclass(frozen=True)
class Message:
    """One message of the catalogue in both languages.

    Attributes
    ----------
    en : str
        English text.
    pl : str
        Polish text.
    hint_en : str or None
        English line telling how to fix the problem.
    hint_pl : str or None
        Polish line telling how to fix the problem.
    """

    en: str
    pl: str
    hint_en: str | None = None
    hint_pl: str | None = None

    def text(self, lang: Language) -> str:
        """Return the text in ``lang``."""
        return self.pl if lang == "pl" else self.en

    def hint(self, lang: Language) -> str | None:
        """Return the hint in ``lang``, or None when the message has none."""
        return self.hint_pl if lang == "pl" else self.hint_en


MESSAGES: Final[dict[str, Message]] = {
    # --- Request validation and the framework ---
    "invalid_request": Message(
        "The request has invalid values: {fields}.",
        "Żądanie zawiera nieprawidłowe wartości: {fields}.",
        "See errors[] for each value.",
        "Szczegóły każdej wartości są w errors[].",
    ),
    "route_not_found": Message(
        "No such route: {path}.",
        "Nie ma takiej trasy: {path}.",
    ),
    "method_not_supported": Message(
        "{method} is not supported on {path}.",
        "Metoda {method} nie jest obsługiwana dla {path}.",
        "Allowed methods: {allowed}.",
        "Dozwolone metody: {allowed}.",
    ),
    "http_error": Message(
        "The request failed with HTTP status {status}.",
        "Żądanie zakończyło się statusem HTTP {status}.",
    ),
    "internal_error": Message(
        "An internal error occurred.",
        "Wystąpił błąd wewnętrzny.",
        "Try again later; if it persists, report the X-Request-ID header of the "
        "response.",
        "Spróbuj ponownie później; jeśli błąd się powtarza, zgłoś nagłówek "
        "X-Request-ID tej odpowiedzi.",
    ),
    # --- Admin authentication ---
    "admin_key_missing": Message(
        "The admin API key is missing.",
        "Brak klucza API administratora.",
        "Send it in the X-Admin-Key header.",
        "Wyślij go w nagłówku X-Admin-Key.",
    ),
    "admin_key_invalid": Message(
        "The admin API key is invalid.",
        "Nieprawidłowy klucz API administratora.",
        "Send the configured key in the X-Admin-Key header.",
        "Wyślij skonfigurowany klucz w nagłówku X-Admin-Key.",
    ),
    # --- Admin panel ---
    "unknown_cleanup_target": Message(
        "Unknown cleanup target: {target}.",
        "Nieznany cel czyszczenia: {target}.",
        "Use one of: {allowed}.",
        "Użyj jednego z: {allowed}.",
    ),
    "filename_missing": Message(
        "No filename was provided.",
        "Nie podano nazwy pliku.",
        "Send the file in the `file` field of a multipart form.",
        "Wyślij plik w polu `file` formularza multipart.",
    ),
    "invalid_file_type": Message(
        "Invalid file type: {suffix}. Allowed: {allowed}.",
        "Nieprawidłowy typ pliku: {suffix}. Dozwolone: {allowed}.",
    ),
    "file_too_large": Message(
        "File too large: {size_mb:.1f} MB (maximum {max_mb} MB).",
        "Plik jest za duży: {size_mb:.1f} MB (maksimum {max_mb} MB).",
    ),
    "invalid_filename": Message(
        "Invalid filename.",
        "Nieprawidłowa nazwa pliku.",
    ),
    "invalid_boundary_file": Message(
        "Invalid boundary file: {cause}",
        "Nieprawidłowy plik granicy: {cause}",
    ),
    "invalid_geodata": Message(
        "The uploaded file is not valid geodata.",
        "Wgrany plik nie zawiera poprawnych danych przestrzennych.",
    ),
    "boundary_file_missing": Message(
        "Boundary file not found: {filename}.",
        "Nie znaleziono pliku granicy: {filename}.",
        "Upload the boundary file first.",
        "Najpierw wgraj plik granicy.",
    ),
    "bootstrap_running": Message(
        "Bootstrap is already running.",
        "Bootstrap jest już uruchomiony.",
        "Wait for it to finish or cancel it.",
        "Poczekaj na jego zakończenie albo anuluj go.",
    ),
    "bootstrap_not_running": Message(
        "No bootstrap process is running.",
        "Żaden proces bootstrap nie jest uruchomiony.",
    ),
    "bootstrap_source_required": Message(
        "Exactly one of bbox, sheets or boundary_file must be provided.",
        "Podaj dokładnie jedno z: bbox, sheets, boundary_file.",
    ),
    "invalid_sheet_code": Message(
        "Invalid sheet code: {sheet}.",
        "Nieprawidłowe godło arkusza: {sheet}.",
    ),
    "invalid_bbox": Message(
        "Invalid bbox: {cause}.",
        "Nieprawidłowy bbox: {cause}.",
        "Use min_lon,min_lat,max_lon,max_lat in WGS84.",
        "Użyj formatu min_lon,min_lat,max_lon,max_lat w WGS84.",
    ),
    "bootstrap_start_failed": Message(
        "Cannot start bootstrap: {cause}",
        "Nie można uruchomić bootstrapu: {cause}",
    ),
    "path_outside_project": Message(
        "The path must be within the project directory.",
        "Ścieżka musi leżeć w katalogu projektu.",
    ),
    "source_file_missing": Message(
        "File not found: {path}.",
        "Nie znaleziono pliku: {path}.",
    ),
    # --- Feedback ---
    "feedback_not_found": Message(
        "Feedback {feedback_id} not found.",
        "Nie znaleziono zgłoszenia {feedback_id}.",
    ),
    "feedback_store_failed": Message(
        "The feedback could not be stored.",
        "Nie udało się zapisać zgłoszenia.",
        "Try again later.",
        "Spróbuj ponownie później.",
    ),
    "feedback_list_failed": Message(
        "The feedback list could not be read.",
        "Nie udało się odczytać listy zgłoszeń.",
    ),
    "feedback_update_failed": Message(
        "The feedback could not be updated.",
        "Nie udało się zaktualizować zgłoszenia.",
    ),
    "feedback_delete_failed": Message(
        "The feedback could not be deleted.",
        "Nie udało się usunąć zgłoszenia.",
    ),
    # --- Watershed and hydrograph ---
    "catchment_graph_unavailable": Message(
        "The catchment graph is not loaded.",
        "Graf zlewni nie został załadowany.",
        "Try again in a moment.",
        "Spróbuj ponownie za chwilę.",
    ),
    "no_catchment_at_point": Message(
        "No catchment at this point.",
        "Nie znaleziono zlewni cząstkowej w tym miejscu.",
        "Click inside a catchment area.",
        "Kliknij w obszarze zlewni.",
    ),
    "catchment_too_large": Message(
        "The catchment ({area_km2:.1f} km²) exceeds the SCS-CN limit of "
        "{limit_km2} km².",
        "Zlewnia ({area_km2:.1f} km²) przekracza limit SCS-CN ({limit_km2} km²).",
        "Choose a point that drains a smaller catchment.",
        "Wybierz punkt, który odwadnia mniejszą zlewnię.",
    ),
    "boundary_build_failed": Message(
        "The catchment boundary could not be built.",
        "Nie udało się zbudować granicy zlewni.",
    ),
    "delineation_failed": Message(
        "The watershed could not be delineated.",
        "Nie udało się wyznaczyć zlewni.",
    ),
    "lutz_parameters_missing": Message(
        "The Lutz method needs channel_length_km, length_to_centroid_km and "
        "channel_slope_m_per_m.",
        "Metoda Lutza wymaga channel_length_km, length_to_centroid_km i "
        "channel_slope_m_per_m.",
    ),
    "snyder_parameters_missing": Message(
        "The Snyder model needs channel_length_km and length_to_centroid_km in the "
        "catchment parameters.",
        "Model Snydera wymaga channel_length_km i length_to_centroid_km w "
        "parametrach zlewni.",
    ),
    "no_precipitation_data": Message(
        "No precipitation data for ({latitude:.4f}, {longitude:.4f}).",
        "Brak danych opadowych dla ({latitude:.4f}, {longitude:.4f}).",
    ),
    "unknown_hietogram_type": Message(
        "Unknown hietogram type: {value}.",
        "Nieznany typ hietogramu: {value}.",
        "Use one of: {allowed}.",
        "Użyj jednego z: {allowed}.",
    ),
    "invalid_parameters": Message(
        "Invalid parameters: {cause}",
        "Nieprawidłowe parametry: {cause}",
    ),
    "hydrograph_failed": Message(
        "The hydrograph could not be generated.",
        "Nie udało się wygenerować hydrogramu.",
    ),
    # --- Terrain profile and depressions ---
    "profile_geometry_type": Message(
        "The geometry must be a GeoJSON LineString.",
        "Geometria musi być obiektem GeoJSON typu LineString.",
    ),
    "profile_too_few_coordinates": Message(
        "A LineString needs at least 2 coordinates.",
        "LineString wymaga co najmniej 2 współrzędnych.",
    ),
    "dem_unavailable": Message(
        "The DEM raster is not available.",
        "Raster NMT nie jest dostępny.",
        "Contact the administrator.",
        "Skontaktuj się z administratorem.",
    ),
    "no_elevation_data": Message(
        "There is no elevation data for the line.",
        "Brak danych wysokościowych dla podanej linii.",
    ),
    "profile_failed": Message(
        "The terrain profile could not be extracted.",
        "Nie udało się wyznaczyć profilu terenu.",
    ),
    "depressions_failed": Message(
        "The depressions could not be read.",
        "Nie udało się odczytać zagłębień terenu.",
    ),
}


class _Params(dict[str, Any]):
    """Format parameters that leave an unknown ``{name}`` field as it is."""

    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def render(template: str, details: Mapping[str, Any]) -> str:
    """Fill the ``{name}`` fields of ``template`` from ``details``.

    A list or tuple is written as its items joined with a comma; a field that
    ``details`` lacks stays in the text.

    Parameters
    ----------
    template : str
        Text of a message or of its hint.
    details : Mapping[str, Any]
        Details of the error.

    Returns
    -------
    str
        The text with the fields filled in.
    """
    params = _Params(
        {
            key: ", ".join(map(str, value))
            if isinstance(value, list | tuple)
            else value
            for key, value in details.items()
        }
    )
    try:
        return template.format_map(params)
    except (ValueError, TypeError):
        # A missing field that has a number format (`{size_mb:.1f}`): keep the text.
        return template
