"""Message catalogue of the errors of the REST API and the scripts (ERR-6, AGI-6.4).

Code refers to a message by its English ID. Each message has an English text, which
answers requests without ``Accept-Language`` and fills the error document of a script
(AGI-9.2), and a Polish text for ``Accept-Language: pl`` (the interface sends it) and
for the human-readable lines of a script. A text may use ``{name}`` fields, which the
details of the error fill in; a message may also carry a hint, the one line that tells
how to fix the call (ERR-5). Codes, ``details`` keys and reasons do not depend on the
language.
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
    "delineation_preview_failed": Message(
        "The watershed preview could not be built.",
        "Nie udało się wyznaczyć podglądu zlewni.",
    ),
    "precise_window_too_large": Message(
        "The watershed of this point is too large for the precise mode: its window "
        "of the rasters has {cells} cells, more than the {max_cells} allowed.",
        "Zlewnia tego punktu jest za duża dla trybu dokładnego: jej okno rastrów ma "
        "{cells} komórek, więcej niż dopuszczalne {max_cells}.",
        "Give threshold_m2 to delineate it from the precomputed sub-catchments.",
        "Podaj threshold_m2, by wyznaczyć ją ze zlewni cząstkowych.",
    ),
    "raster_grids_differ": Message(
        "The DEM is not on the grid of the flow directions: its transform or its "
        "shape differs.",
        "Raster NMT nie leży na siatce kierunków spływu: ma inną transformację albo "
        "inne wymiary.",
        "Contact the administrator.",
        "Skontaktuj się z administratorem.",
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
    "pmaxtp_grid_point_unknown": Message(
        "pmaxtp_grid has no PMAXTP grid point at ({easting_m}, {northing_m}) "
        "EPSG:2180.",
        "pmaxtp_grid nie ma punktu siatki PMAXTP w ({easting_m}, {northing_m}) "
        "EPSG:2180.",
        "Send the pmaxtp_grid of a delineation of this server, or leave it out to "
        "interpolate the depth at the point.",
        "Wyślij pmaxtp_grid z wyznaczenia zlewni na tym serwerze albo pomiń je, by "
        "interpolować opad w punkcie.",
    ),
    "unknown_hietogram_type": Message(
        "Unknown hietogram type: {value}.",
        "Nieznany typ hietogramu: {value}.",
        "Use one of: {allowed}.",
        "Użyj jednego z: {allowed}.",
    ),
    "tc_inputs_missing": Message(
        "The time of concentration by the {method} method needs: {missing}.",
        "Czas koncentracji metodą {method} wymaga: {missing}.",
        "Give tc_runoff_coeff (FAA's C) or tc_retardance (Kerby's N) in the request "
        "and the missing watershed fields in the morphometry (advanced mode), or "
        "choose another method.",
        "Podaj w żądaniu tc_runoff_coeff (C metody FAA) albo tc_retardance (N metody "
        "Kerby'ego), a brakujące parametry zlewni w morfometrii (tryb zaawansowany), "
        "albo wybierz inną metodę.",
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
    # --- Point identification ---
    "no_data_at_point": Message(
        "There is no data at this point: it lies outside the area of Hydrograf's data.",
        "Brak danych w tym miejscu: punkt leży poza obszarem danych Hydrografu.",
        "Click inside the area covered by the data.",
        "Kliknij w obszarze objętym danymi.",
    ),
    "identify_failed": Message(
        "The information about the point could not be read.",
        "Nie udało się odczytać informacji o punkcie.",
    ),
    # --- Bootstrap: the shared store and the sets of Archiwista projects (ADR-067) ---
    "bootstrap_arguments_invalid": Message(
        "Invalid arguments: {cause}.",
        "Nieprawidłowe argumenty: {cause}.",
        "See python -m scripts.bootstrap --help.",
        "Zobacz python -m scripts.bootstrap --help.",
    ),
    "shared_store_read_only": Message(
        "The Kartograf store {root} is shared with Archiwista and Hydrograf only reads "
        "it: nothing is downloaded into it.",
        "Magazyn Kartografa {root} jest wspólny z Archiwistą i Hydrograf tylko z niego "
        "czyta: nic nie jest do niego pobierane.",
        "Bootstrap from a set of an Archiwista project (--project and --set), or unset "
        "HYDROGRAF_KARTOGRAF_ROOT to download into <cache_dir>/kartograf.",
        "Uruchom bootstrap z zestawu projektu Archiwisty (--project i --set) albo usuń "
        "HYDROGRAF_KARTOGRAF_ROOT, aby pobierać do <cache_dir>/kartograf.",
    ),
    "project_file_missing": Message(
        "There is no Archiwista project file archiwista-project.json in {path}.",
        "W {path} nie ma pliku projektu Archiwisty archiwista-project.json.",
        "Give the directory of the project that its card in Archiwista shows.",
        "Podaj katalog projektu pokazany na jego karcie w Archiwiście.",
    ),
    "project_schema_unsupported": Message(
        "The project file has the schema {schema}; Hydrograf reads "
        "archiwista-project/1.",
        "Plik projektu ma schemat {schema}; Hydrograf czyta archiwista-project/1.",
        "Use a newer Hydrograf.",
        "Użyj nowszej wersji Hydrografa.",
    ),
    "project_file_invalid": Message(
        "The project file {path} breaks the rule {rule} of archiwista-project/1 at the "
        "JSON pointer '{pointer}'.",
        "Plik projektu {path} narusza regułę {rule} formatu archiwista-project/1 we "
        "wskaźniku JSON '{pointer}'.",
        "Open the project's card in Archiwista: it names the problem.",
        "Otwórz kartę projektu w Archiwiście: wskaże problem.",
    ),
    "file_unreadable": Message(
        "{path} cannot be read: {cause}",
        "Nie można odczytać {path}: {cause}",
        "Grant the bootstrap read access to the project and the store (ADR-067).",
        "Nadaj bootstrapowi prawo odczytu projektu i magazynu (ADR-067).",
    ),
    "project_area_unset": Message(
        "The project {project} has no area.",
        "Projekt {project} nie ma obszaru.",
        "In Archiwista, set the project's area on its card.",
        "Ustaw obszar projektu na jego karcie w Archiwiście.",
    ),
    "project_area_missing": Message(
        "The area file {path} of the project is missing.",
        "Brak pliku obszaru projektu {path}.",
        "In Archiwista, set the project's area again on its card.",
        "Ustaw obszar projektu ponownie na jego karcie w Archiwiście.",
    ),
    "project_area_changed": Message(
        "The area file {path} changed after Archiwista recorded it (SHA-256 {actual}, "
        "recorded {expected}).",
        "Plik obszaru {path} zmienił się po zapisaniu przez Archiwistę (SHA-256 "
        "{actual}, zapisany {expected}).",
        "In Archiwista, set the project's area again on its card.",
        "Ustaw obszar projektu ponownie na jego karcie w Archiwiście.",
    ),
    "project_area_unreadable": Message(
        "The area file {path} cannot be read as an area: {cause}",
        "Nie można odczytać pliku obszaru {path} jako obszaru: {cause}",
        "In Archiwista, set the project's area again on its card.",
        "Ustaw obszar projektu ponownie na jego karcie w Archiwiście.",
    ),
    "set_not_found": Message(
        "The project {project} has no set {name}.",
        "Projekt {project} nie ma zestawu {name}.",
        "Name one of its sets (letter case does not matter): {sets}.",
        "Podaj jeden z jego zestawów (wielkość liter nie ma znaczenia): {sets}.",
    ),
    "set_open": Message(
        "The set {name} is open: it is being built in Archiwista, and Hydrograf reads "
        "only closed sets.",
        "Zestaw {name} jest otwarty: jest w budowie w Archiwiście, a Hydrograf czyta "
        "tylko zamknięte zestawy.",
        "Close it in Archiwista: „Zamknij zestaw” on the project's card.",
        "Zamknij go w Archiwiście: „Zamknij zestaw” na karcie projektu.",
    ),
    "set_digest_mismatch": Message(
        "The pins of the set {name} do not match its pins_sha256 (recorded {expected}, "
        "computed {actual}): the project file was changed outside Archiwista.",
        "Piny zestawu {name} nie zgadzają się z jego pins_sha256 (zapisany {expected}, "
        "obliczony {actual}): plik projektu zmieniono poza Archiwistą.",
        "In Archiwista, check the set („Weryfikuj”), then „Otwórz do edycji” and "
        "„Zamknij zestaw” to record its pins again.",
        "Sprawdź zestaw w Archiwiście („Weryfikuj”), potem „Otwórz do edycji” i "
        "„Zamknij zestaw”, aby zapisać jego piny na nowo.",
    ),
    "project_store_unset": Message(
        "The project {project} names no Kartograf store.",
        "Projekt {project} nie wskazuje magazynu Kartografa.",
        "In Archiwista, choose the project's store („Zmień…” on its card).",
        "Wybierz magazyn projektu w Archiwiście („Zmień…” na jego karcie).",
    ),
    "project_store_unusable": Message(
        "The project's Kartograf store {root} cannot be used ({state}).",
        "Nie można użyć magazynu Kartografa projektu {root} ({state}).",
        "Check that the store is mounted at this path, or change the project's store "
        "in Archiwista („Zmień…”).",
        "Sprawdź, czy magazyn jest zamontowany pod tą ścieżką, albo zmień magazyn "
        "projektu w Archiwiście („Zmień…”).",
    ),
    "project_store_mismatch": Message(
        "The project's Kartograf store {root} is not the store {shared} that "
        "HYDROGRAF_KARTOGRAF_ROOT names.",
        "Magazyn Kartografa projektu {root} to nie magazyn {shared} wskazany przez "
        "HYDROGRAF_KARTOGRAF_ROOT.",
        "Mount the project's store at its own path and set HYDROGRAF_KARTOGRAF_ROOT "
        "to it.",
        "Zamontuj magazyn projektu pod jego własną ścieżką i ustaw na nią "
        "HYDROGRAF_KARTOGRAF_ROOT.",
    ),
    "pins_missing": Message(
        "Pinned files of the set {name} missing from the store {root}: {count}.",
        "Przypięte pliki zestawu {name}, których brakuje w magazynie {root}: {count}.",
        "In Archiwista, restore them: „Przywróć brakujące” of the set "
        "(archiwista project-restore).",
        "Przywróć je w Archiwiście: „Przywróć brakujące” w zestawie "
        "(archiwista project-restore).",
    ),
    "pins_changed": Message(
        "Pinned files of the set {name} whose size or SHA-256 differs from the pin: "
        "{count}.",
        "Przypięte pliki zestawu {name}, których rozmiar lub SHA-256 różni się od "
        "pinu: {count}.",
        "In Archiwista, check the set („Weryfikuj”, archiwista project-verify), then "
        "„Przywróć brakujące”.",
        "Sprawdź zestaw w Archiwiście („Weryfikuj”, archiwista project-verify), potem "
        "„Przywróć brakujące”.",
    ),
    "pins_unreadable": Message(
        "Pinned files of the set {name} that cannot be read: {count} ({cause}).",
        "Przypięte pliki zestawu {name}, których nie można odczytać: {count} "
        "({cause}).",
        "Grant the bootstrap read access to the store (ADR-067).",
        "Nadaj bootstrapowi prawo odczytu magazynu (ADR-067).",
    ),
    "set_sheets_missing": Message(
        "NMT sheets ({resolution}) of the project's area that the set {name} lacks: "
        "{count}.",
        "Arkusze NMT ({resolution}) obszaru projektu, których brakuje w zestawie "
        "{name}: {count}.",
        "In Archiwista: „Otwórz do edycji”, add an elevation download over the "
        "project's area, then „Zamknij zestaw”.",
        "W Archiwiście: „Otwórz do edycji”, dodaj polecenie elevation download na "
        "obszarze projektu, potem „Zamknij zestaw”.",
    ),
    "set_counties_missing": Message(
        "Counties of the NMT mosaic whose BDOT10k package the set {name} lacks: "
        "{count}.",
        "Powiaty mozaiki NMT, których paczki BDOT10k brakuje w zestawie {name}: "
        "{count}.",
        "In Archiwista: „Otwórz do edycji”, add a landcover download over the "
        "project's area, then „Zamknij zestaw”.",
        "W Archiwiście: „Otwórz do edycji”, dodaj polecenie landcover download na "
        "obszarze projektu, potem „Zamknij zestaw”.",
    ),
    "set_hsg_missing": Message(
        "The set {name} has no HSG raster of {segment} (soil.hsg_depth_rule "
        "{depth_rule}) that covers the NMT mosaic.",
        "Zestaw {name} nie ma rastra HSG z {segment} (soil.hsg_depth_rule "
        "{depth_rule}) pokrywającego mozaikę NMT.",
        "In Archiwista: „Otwórz do edycji”, add the call {command}, then „Zamknij "
        "zestaw”.",
        "W Archiwiście: „Otwórz do edycji”, dodaj polecenie {command}, potem "
        "„Zamknij zestaw”.",
    ),
    "nmt_coverage_gap": Message(
        "The NMT sheets leave {area_km2} km² of the area, or of the inside of their "
        "mosaic, without data; missing sheets ({count}): {sheets}.",
        "Arkusze NMT zostawiają bez danych {area_km2} km² obszaru lub wnętrza ich "
        "mozaiki; brakujące arkusze ({count}): {sheets}.",
        "Add the missing sheets (in Archiwista: „Otwórz do edycji”, an elevation "
        "download over them, „Zamknij zestaw”), or run with --allow-uncovered "
        "(ADR-076).",
        "Dodaj brakujące arkusze (w Archiwiście: „Otwórz do edycji”, polecenie "
        "elevation download na nich, „Zamknij zestaw”) albo uruchom z "
        "--allow-uncovered (ADR-076).",
    ),
    "set_unit_ambiguous": Message(
        "Units with more than one version in the set {name} ({count}): {units}.",
        "Jednostki z więcej niż jedną wersją w zestawie {name} ({count}): {units}.",
        "In Archiwista: „Otwórz do edycji”, keep one version per sheet, county and "
        "raster, then „Zamknij zestaw”.",
        "W Archiwiście: „Otwórz do edycji”, zostaw jedną wersję na arkusz, powiat i "
        "raster, potem „Zamknij zestaw”.",
    ),
    "prg_unavailable": Message(
        "The county register (PRG) did not answer: {cause}",
        "Rejestr powiatów (PRG) nie odpowiedział: {cause}",
        "Try again later.",
        "Spróbuj ponownie później.",
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
