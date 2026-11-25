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
        "Try again later; if it persists, report it with the date and time of the "
        "request.",
        "Spróbuj ponownie później; jeśli błąd się powtarza, zgłoś go, podając datę "
        "i godzinę żądania.",
    ),
    # --- Admin authentication ---
    "admin_key_not_configured": Message(
        "No admin API key is set on the server.",
        "Serwer nie ma ustawionego klucza administratora.",
        "Start the API with ADMIN_API_KEY or ADMIN_API_KEY_FILE.",
        "Uruchom API z ADMIN_API_KEY albo ADMIN_API_KEY_FILE.",
    ),
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
    "stats_period_reversed": Message(
        "The period ends before it begins: from {first} to {last}.",
        "Okres kończy się przed początkiem: od {first} do {last}.",
        "Give `from` no later than `to`.",
        "Podaj `from` nie późniejsze niż `to`.",
    ),
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
    # --- The public service (ADR-084) ---
    "request_limit": Message(
        "Too many requests. Try again in {retry_after_s} s.",
        "Zbyt wiele żądań. Spróbuj ponownie za {retry_after_s} s.",
    ),
    "terms_not_configured": Message(
        "This deployment serves no terms of use.",
        "To wdrożenie nie udostępnia regulaminu.",
    ),
    # --- The catalog and the jobs of /api/v1 (ADR-091) ---
    "unknown_command": Message(
        "Hydrograf has no command {command}.",
        "Hydrograf nie ma polecenia {command}.",
        "Commands: {allowed}.",
        "Polecenia: {allowed}.",
    ),
    "run_as_job": Message(
        "{command} runs only as a job: its run can outlast a request.",
        "{command} działa tylko jako zadanie: obliczenie może trwać dłużej niż "
        "żądanie.",
        'Start it with POST /api/v1/jobs {{"command": "{command}", "options": '
        "{{…}}}} and follow jobs/<id>.",
        'Uruchom je przez POST /api/v1/jobs {{"command": "{command}", "options": '
        "{{…}}}} i śledź jobs/<id>.",
    ),
    "not_a_job": Message(
        "{command} is not served as a job.",
        "{command} nie jest uruchamiane jako zadanie.",
        "Call its route {path}; jobs run {allowed}.",
        "Wywołaj jego trasę {path}; jako zadania działają: {allowed}.",
    ),
    "job_limit": Message(
        "{limit} of your jobs are running already.",
        "Trwają już {limit} Twoje obliczenia.",
        "Wait until one ends, or cancel one, then start the next.",
        "Poczekaj, aż jedno się skończy, albo anuluj je i uruchom następne.",
    ),
    "job_expired": Message(
        "This server keeps no job {job_id}: a job is kept an hour after it ends and "
        "a restart of the server forgets the ended ones.",
        "Ten serwer nie przechowuje zadania {job_id}: zadanie jest przechowywane "
        "godzinę po zakończeniu, a restart serwera usuwa zakończone.",
        "Start the job again.",
        "Uruchom zadanie ponownie.",
    ),
    "job_running": Message(
        "The job {job_id} has not ended yet.",
        "Zadanie {job_id} jeszcze się nie zakończyło.",
        "Ask for its result once GET jobs/{job_id} shows that it ended.",
        "Poproś o wynik, gdy GET jobs/{job_id} pokaże, że się zakończyło.",
    ),
    "job_interrupted": Message(
        "The job {job_id} was interrupted by a restart of the server and has no "
        "result.",
        "Zadanie {job_id} przerwał restart serwera; nie ma wyniku.",
        "Start the job again.",
        "Uruchom zadanie ponownie.",
    ),
    "job_failed": Message(
        "The job could not be run.",
        "Nie udało się wykonać zadania.",
    ),
    # --- Settings of the deployment ---
    "basemap_catalogue_unreadable": Message(
        "The kit's catalogue of base maps cannot be read: {path}.",
        "Nie można odczytać katalogu podkładów zestawu: {path}.",
        "Copy nogat-basemaps.json from Nogat's kit into frontend/nogat/ again, byte "
        "for byte.",
        "Skopiuj ponownie nogat-basemaps.json z zestawu Nogat do frontend/nogat/, "
        "bajt w bajt.",
    ),
    "basemap_unknown": Message(
        "{option} of {source} names a base map the kit's catalogue does not have: "
        "{value}.",
        "{option} w {source} wskazuje podkład, którego nie ma w katalogu zestawu: "
        "{value}.",
        "Use the ids of the catalogue: {known}.",
        "Użyj identyfikatorów z katalogu: {known}.",
    ),
    "basemaps_invalid": Message(
        "basemaps of {source} is not a list of base map ids: {value}.",
        "basemaps w {source} nie jest listą identyfikatorów podkładów: {value}.",
        'Give a list of texts, e.g. basemaps = ["openfreemap", "gugik-ortho"]; '
        "[] offers none.",
        'Podaj listę tekstów, np. basemaps = ["openfreemap", "gugik-ortho"]; '
        "[] nie udostępnia żadnego podkładu.",
    ),
    "basemap_mirrors_invalid": Message(
        "basemap_mirrors of {source} has a wrong value: {value}.",
        "basemap_mirrors w {source} ma błędną wartość: {value}.",
        "Give a table of catalogue ids to the http or https addresses of the "
        "deployment's copies, e.g. basemap_mirrors = {{ openfreemap = "
        '"https://tiles.example.org/planet" }}.',
        "Podaj tabelę identyfikatorów z katalogu i adresów http lub https kopii "
        "wdrożenia, np. basemap_mirrors = {{ openfreemap = "
        '"https://tiles.example.org/planet" }}.',
    ),
    "basemap_extra_invalid": Message(
        "basemap_extra of {source} has a wrong {field}: {value}.",
        "basemap_extra w {source} ma błędną wartość {field}: {value}.",
        "Give a list of tables with id, name, kind (xyz, wms or vector), url (http "
        "or https), attribution and, optionally, grayscale (true or false); each id "
        "unique, not none and not an id of the kit's catalogue.",
        "Podaj listę tabel z id, name, kind (xyz, wms albo vector), url (http lub "
        "https), attribution i opcjonalnie grayscale (true albo false); każde id "
        "niepowtarzalne, inne niż none i niż identyfikatory katalogu zestawu.",
    ),
    "basemap_extra_missing": Message(
        "An own base map of basemap_extra in {source} has no {field}: {value}.",
        "Własny podkład z basemap_extra w {source} nie ma pola {field}: {value}.",
        "Give a list of tables with id, name, kind (xyz, wms or vector), url (http "
        "or https), attribution and, optionally, grayscale (true or false); each id "
        "unique, not none and not an id of the kit's catalogue.",
        "Podaj listę tabel z id, name, kind (xyz, wms albo vector), url (http lub "
        "https), attribution i opcjonalnie grayscale (true albo false); każde id "
        "niepowtarzalne, inne niż none i niż identyfikatory katalogu zestawu.",
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
    # --- Network delineation (ADR-080) ---
    "network_point_off_stream": Message(
        "Point {point_id} lies more than {snap_m:g} m from a stream of the "
        "{threshold_m2} m² network.",
        "Punkt {point_id} leży dalej niż {snap_m:g} m od cieku sieci "
        "{threshold_m2} m².",
        "Place the point on a stream drawn on the map.",
        "Postaw punkt na cieku narysowanym na mapie.",
    ),
    "network_point_outside": Message(
        "Point {point_id} does not drain to the closing section {outlet_id}.",
        "Punkt {point_id} nie odwadnia się do przekroju zamykającego {outlet_id}.",
        "Move the point onto a stream above the closing section.",
        "Przesuń punkt na ciek powyżej przekroju zamykającego.",
    ),
    "network_points_coincide": Message(
        "Points {point_ids} fall on the same node of the network: one point at a "
        "node already divides the catchment into the streams that join there.",
        "Punkty {point_ids} trafiają w ten sam węzeł sieci: jeden punkt w węźle już "
        "dzieli zlewnię na cieki, które się w nim łączą.",
        "Remove one of them or move it more than 50 m from the node.",
        "Usuń jeden z nich albo przesuń go dalej niż 50 m od węzła.",
    ),
    "network_window_too_large": Message(
        "The catchment of the closing section is too large for a network: its "
        "window of the rasters has {cells} cells, more than the {max_cells} allowed.",
        "Zlewnia przekroju zamykającego jest za duża dla sieci: jej okno rastrów ma "
        "{cells} komórek, więcej niż dopuszczalne {max_cells}.",
        "Choose a closing section that drains a smaller catchment.",
        "Wybierz przekrój zamykający, który odwadnia mniejszą zlewnię.",
    ),
    "network_rasters_missing": Message(
        "Rasters of the network delineation are missing: {rasters}.",
        "Brakuje rastrów do wyznaczenia sieci: {rasters}.",
        "Contact the administrator.",
        "Skontaktuj się z administratorem.",
    ),
    "network_area_mismatch": Message(
        "The elements of the network do not add up to the catchment of the closing "
        "section: {elements_cells} cells against {watershed_cells}.",
        "Elementy sieci nie sumują się do zlewni przekroju zamykającego: "
        "{elements_cells} komórek wobec {watershed_cells}.",
    ),
    "network_delineation_busy": Message(
        "Another network is being delineated: this request waited {wait_s:g} s.",
        "Trwa wyznaczanie innej sieci: to żądanie czekało {wait_s:g} s.",
        "Try again in a moment.",
        "Spróbuj ponownie za chwilę.",
    ),
    "network_delineation_failed": Message(
        "The network could not be delineated.",
        "Nie udało się wyznaczyć sieci.",
    ),
    "network_preview_failed": Message(
        "The preview of the network could not be built.",
        "Nie udało się zbudować podglądu sieci.",
    ),
    "lutz_parameters_missing": Message(
        "The Lutz method needs flow_path_length_km, length_to_centroid_km and "
        "flow_path_equal_area_slope_m_per_m.",
        "Metoda Lutza wymaga flow_path_length_km, length_to_centroid_km i "
        "flow_path_equal_area_slope_m_per_m.",
        "Delineate the watershed on this server, whose filled DEM gives the "
        "equal-area slope of the longest flow path, or give it in the morphometry.",
        "Wyznacz zlewnię na tym serwerze, którego NMT daje spadek wyrównany "
        "najdłuższej drogi spływu, albo podaj go w morfometrii.",
    ),
    "snyder_parameters_missing": Message(
        "The Snyder model needs flow_path_length_km and length_to_centroid_km in the "
        "catchment parameters.",
        "Model Snydera wymaga flow_path_length_km i length_to_centroid_km w "
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
    "unknown_attribution_line": Message(
        "custom_precipitation brings the line „{line}”, which is not a line of the "
        "{provider} data that derived_from names.",
        "Seria opadu przynosi linię „{line}”, która nie jest linią danych {provider} "
        "wskazanych w derived_from.",
        "Send the lines of the file the series was read from unchanged, as "
        "Obserwator's series export writes them; export a file of an older Obserwator "
        "again.",
        "Wyślij linie pliku, z którego pochodzi seria, bez zmian, tak jak zapisuje je "
        "eksport szeregu Obserwatora; plik starszego Obserwatora wyeksportuj ponownie.",
    ),
    "attribution_line_without_origin": Message(
        "custom_precipitation brings the line „{line}” without derived_from, which "
        "names the data the series came from.",
        "Seria opadu przynosi linię „{line}” bez derived_from, które wskazuje dane, z "
        "których pochodzi seria.",
        "Set derived_from to imgw, chmu or pmaxtp, or leave the lines out for data of "
        "your own.",
        "Ustaw derived_from na imgw, chmu albo pmaxtp albo pomiń linie przy danych "
        "własnych.",
    ),
    "storm_not_whole_steps": Message(
        "The duration of {duration_min:g} min is not a whole number of time steps of "
        "{timestep_min:g} min: a design hyetograph is made of whole steps.",
        "Czas trwania {duration_min:g} min nie jest wielokrotnością kroku czasowego "
        "{timestep_min:g} min: hietogram projektowy składa się z całych kroków.",
        "Choose a time step that divides the duration: 5 min divides every PMAXTP "
        "duration.",
        "Wybierz krok, który dzieli czas trwania: 5 min dzieli każdy czas trwania "
        "PMAXTP.",
    ),
    "euler_ii_step_below_curve": Message(
        "Euler II is built from the PMAXTP depth-duration curve, which starts at "
        "{shortest_min:g} min: the time step of {timestep_min:g} min is shorter.",
        "Euler II buduje się z krzywej wysokość–czas trwania PMAXTP, która zaczyna się "
        "od {shortest_min:g} min: krok czasowy {timestep_min:g} min jest krótszy.",
        "Choose a time step of at least {shortest_min:g} min that divides the "
        "duration, or another hyetograph.",
        "Wybierz krok co najmniej {shortest_min:g} min, który dzieli czas trwania, "
        "albo inny rozkład opadu.",
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
    # Hydrolog's refusals by the reasons of Nogat's computation standard (CMP-3.1,
    # CMP-3.2; core/hydrolog_refusals.py)
    "formula_input_outside_physical_range": Message(
        "{option} = {value} is outside its physical range {range} (formula {formula}).",
        "Wartość {option} = {value} jest poza zakresem fizycznym {range} (wzór "
        "{formula}).",
    ),
    "formula_input_invalid_type": Message(
        "{option} is not a number (formula {formula}).",
        "{option} nie jest liczbą (wzór {formula}).",
    ),
    "formula_physical_condition": Message(
        "A physical condition of the formula {formula} is not met ({constraint}): "
        "{text}",
        "Niespełniony warunek fizyczny wzoru {formula} ({constraint}): {text}",
    ),
    "formula_precondition_failed": Message(
        "A condition of applicability of the formula {formula} is not met "
        "({constraint}): {text}",
        "Niespełniony warunek stosowalności wzoru {formula} ({constraint}): {text}",
    ),
    "lutz_centroid_beyond_length": Message(
        "Lutz's method: the length to the centroid Lc cannot exceed the length of the "
        "longest flow path L: both run from the outlet, Lc along the main channel to "
        "its point nearest the centroid of the watershed, L to the divide.",
        "Metoda Lutza: długość do środka ciężkości zlewni Lc nie może być większa od "
        "długości najdłuższej drogi spływu L: obie biegną od przekroju zamykającego, "
        "Lc wzdłuż cieku głównego do jego punktu najbliższego środka ciężkości "
        "zlewni, L do działu wodnego.",
        "Correct length_to_centroid_km or flow_path_length_km (advanced mode).",
        "Popraw Lc albo najdłuższą drogę spływu (tryb zaawansowany).",
    ),
    "lutz_shares_over_area": Message(
        "Lutz's method: the shares of urbanised land U and of forest W together "
        "cannot exceed 100% of the watershed.",
        "Metoda Lutza: udział terenów zurbanizowanych U i udział lasów W razem nie "
        "mogą przekroczyć 100% powierzchni zlewni.",
        "Correct urban_pct or forest_pct (advanced mode).",
        "Popraw udział terenów zurbanizowanych albo lasów (tryb zaawansowany).",
    ),
    "kerby_kirpich_overland_not_shorter": Message(
        "Kerby-Kirpich: the longest flow path must be longer than its overland "
        "segment: the method times the rest of the path as channel flow.",
        "Kerby–Kirpich: najdłuższa droga spływu musi być dłuższa od spływu "
        "powierzchniowego: metoda liczy resztę drogi jako przepływ korytem.",
        "Choose another method of the time of concentration, or correct "
        "flow_path_length_km or overland_length_km (advanced mode).",
        "Wybierz inną metodę czasu koncentracji albo popraw najdłuższą drogę spływu "
        "lub długość spływu powierzchniowego (tryb zaawansowany).",
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
    # --- The design depth of a catchment (ADR-069, ADR-091) ---
    "boundary_invalid": Message(
        "boundary is not a valid GeoJSON Polygon or MultiPolygon in WGS84: {cause}.",
        "boundary nie jest poprawnym wielokątem GeoJSON (Polygon, MultiPolygon) w "
        "WGS84: {cause}.",
        "Send result.watershed.boundary_geojson of watershed delineate.",
        "Wyślij result.watershed.boundary_geojson z watershed delineate.",
    ),
    "boundary_too_large": Message(
        "The boundary ({area_km2:.1f} km²) exceeds the limit of a design depth, "
        "{limit_km2} km².",
        "Obszar ({area_km2:.1f} km²) przekracza limit opadu miarodajnego "
        "({limit_km2} km²).",
        "Send the boundary of one catchment.",
        "Wyślij granicę jednej zlewni.",
    ),
    "no_design_depth_data": Message(
        "The PMAXTP grid has no data for the boundary at {duration_min} min and "
        "{probability_percent} %.",
        "Siatka PMAXTP nie ma danych dla tego obszaru przy {duration_min} min i "
        "{probability_percent} %.",
        "Send a boundary inside the area of this server's PMAXTP grid.",
        "Wyślij granicę w obszarze siatki PMAXTP tego serwera.",
    ),
    "design_depth_failed": Message(
        "The design depth could not be computed.",
        "Nie udało się obliczyć opadu miarodajnego.",
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
        "project's area (a sheet the source lacks at this resolution: the same sheet "
        "at a finer one, e.g. NMT 1 m), then „Zamknij zestaw”.",
        "W Archiwiście: „Otwórz do edycji”, dodaj polecenie elevation download na "
        "obszarze projektu (arkusz, którego źródło nie ma w tej rozdzielczości: ten "
        "sam arkusz w drobniejszej, np. NMT 1 m), potem „Zamknij zestaw”.",
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
