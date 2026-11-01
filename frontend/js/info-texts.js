/**
 * Hydrograf explanation texts for the (i) markers (js/info.js).
 *
 * Keys are API/morphometry field names (result rows), form control ids
 * (form fields), free keys used with data-info or Hydrograf.info.attach
 * (custom-rain, bdot_coverage) and '<selectId>:<value>' for the options of
 * the UH model, Tc method and Nash estimation selects. Every entry is an
 * object with these optional fields:
 *
 *   title       name of the quantity (the label of the row when missing)
 *   symbol      its symbol, in the formula notation below
 *   definition  what the quantity is
 *   formula     a formula or an array of formulas
 *   variables   rows [symbol, meaning, unit] of the "gdzie:" list
 *   unit        unit of the value
 *   list        { title, items: [[term, text], ...] }, e.g. typical values
 *   meaning     how it influences the runoff and the hydrograph, how to read it
 *   range       applicability (option entries)
 *   note        limits and data caveats
 *   summary     option entries: the compact line under the select
 *
 * Text may hold inline formulas between $...$. Formula notation, typeset
 * as MathML by info.js: x_i, x_{ab} subscript; x^2, x^{0,77} superscript;
 * \frac{a}{b}; \sqrt{a}; \text{...} upright text; { } groups; ( ) and [ ]
 * are fences that take scripts as a whole; a run of Latin letters is one
 * identifier (one letter italic, more letters upright: max, CN); a Greek
 * letter is one identifier; numbers use a decimal comma; '-' is a minus.
 *
 * Every formula, unit and statement follows the code that computes the
 * value: Hydrograf backend (core/catchment_graph.py, core/watershed_service.py,
 * core/morphometry.py, core/land_cover.py, core/precipitation.py,
 * api/endpoints/hydrograph.py) and Hydrolog 0.6.3 (time/concentration.py,
 * runoff/*.py, precipitation/hietogram.py).
 */
(function () {
    'use strict';

    window.Hydrograf = window.Hydrograf || {};

    var f = String.raw;

    // Rows shared by several "gdzie:" lists
    var A = ['A', 'powierzchnia zlewni', 'km²'];
    var P = ['P', 'obwód zlewni', 'km'];
    var L = ['L', 'długość zlewni (najdłuższa droga spływu)', 'km'];
    var H_MAX = ['H_{max}', 'najwyższa wysokość terenu w zlewni', 'm n.p.m.'];
    var H_MIN = ['H_{min}', 'najniższa wysokość terenu w zlewni', 'm n.p.m.'];
    var H_MEAN = ['H_{śr}', 'średnia wysokość terenu zlewni', 'm n.p.m.'];
    var L_G = ['L_g', 'długość cieku głównego', 'km'];
    var L_C = ['L_c', 'długość cieku głównego od ujścia do punktu najbliższego środkowi ciężkości zlewni', 'km'];
    var S = ['S', 'retencja maksymalna zlewni, $S = 25400/CN - 254$', 'mm'];
    var TC = ['T_c', 'czas koncentracji', 'min'];
    var DT = ['Δt', 'krok czasowy obliczeń: 5 min, przy własnej serii opadu – jej krok', 'min'];

    var BETA_PEAK = {
        formula: f`t_s = \frac{α - 1}{α + β - 2}`,
        variables: [
            ['t_s', 'położenie szczytu opadu jako ułamek czasu trwania (dla $α, β > 1$)', '–'],
            ['α, β', 'parametry rozkładu Beta', '–'],
        ],
    };

    window.Hydrograf.infoTexts = {
        // ── Parametry podstawowe ───────────────────────────────────────
        area_km2: {
            title: 'Powierzchnia zlewni',
            symbol: 'A',
            definition: 'Powierzchnia obszaru, z którego woda spływa do ujścia: suma powierzchni zlewni cząstkowych wyznaczonych z NMT – klikniętej i wszystkich położonych powyżej niej.',
            formula: 'A = ∑ A_i',
            variables: [['A_i', 'powierzchnia i-tej zlewni cząstkowej: liczba komórek NMT razy powierzchnia komórki', 'km²']],
            unit: 'km²',
            meaning: 'Skaluje cały odpływ: objętość odpływu to w przybliżeniu $P_e·A$, a przy tych samych parametrach czasowych szczyt hydrogramu jednostkowego jest proporcjonalny do $A$. Hietogram i hydrogram są liczone dla zlewni do 250 km².',
        },
        perimeter_km: {
            title: 'Obwód zlewni',
            symbol: 'P',
            definition: 'Długość granicy zlewni (działu wodnego). Granica powstaje z połączenia zlewni cząstkowych, uproszczonego z tolerancją 5 m i wygładzonego.',
            unit: 'km',
            meaning: 'Wchodzi do wskaźników zwartości $C_z$ i kolistości $C_k$ oraz spadku działu wodnego $R_p$. Nie wpływa na hydrogram.',
            note: 'Uproszczenie i wygładzenie usuwają schodki rastra, więc obwód jest krótszy niż obrys komórek NMT – najbardziej w małych zlewniach.',
        },
        length_km: {
            title: 'Długość zlewni',
            symbol: 'L',
            definition: 'Długość najdłuższej drogi spływu od działu wodnego do ujścia, po kierunkach spływu z NMT. Gdy jej brak – największa odległość w linii prostej od ujścia do granicy zlewni.',
            unit: 'km',
            meaning: 'Wchodzi do wskaźników kształtu $C_w$, $C_f$, $C_l$ i do średniej szerokości $B$. Metody Tc NRCS i Kirpicha używają tej samej najdłuższej drogi spływu.',
        },
        mean_width_km: {
            title: 'Średnia szerokość zlewni',
            symbol: 'B',
            definition: 'Szerokość prostokąta o powierzchni i długości zlewni.',
            formula: f`B = \frac{A}{L}`,
            variables: [A, L],
            unit: 'km',
            meaning: 'Przy tej samej powierzchni mniejsza szerokość oznacza zlewnię bardziej wydłużoną. Wskaźnik opisowy – nie wpływa na hydrogram.',
        },
        elevation_min_m: {
            title: 'Wysokość minimalna',
            symbol: 'H_{min}',
            definition: 'Najniższa wysokość terenu w zlewni według NMT. Hydrograf przyjmuje ją także jako wysokość ujścia.',
            unit: 'm n.p.m.',
            meaning: 'Punkt odniesienia deniwelacji $ΔH = H_{max} - H_{min}$ we wskaźnikach rzeźby ($R$, $R_p$, $R_n$, $HI$). Metoda Giandottiego używa deniwelacji $H_{śr} - H_{min}$.',
        },
        elevation_max_m: {
            title: 'Wysokość maksymalna',
            symbol: 'H_{max}',
            definition: 'Najwyższa wysokość terenu w zlewni według NMT.',
            unit: 'm n.p.m.',
            meaning: 'Wyznacza deniwelację zlewni $ΔH = H_{max} - H_{min}$, używaną we wskaźnikach rzeźby i w liczbie chropowatości.',
        },
        elevation_mean_m: {
            title: 'Wysokość średnia',
            symbol: 'H_{śr}',
            definition: 'Średnia wysokość terenu zlewni: średnie wysokości zlewni cząstkowych ważone ich powierzchnią, czyli w praktyce średnia z komórek NMT.',
            formula: f`H_{śr} = \frac{∑ A_i H_{śr,i}}{∑ A_i}`,
            variables: [
                ['A_i', 'powierzchnia i-tej zlewni cząstkowej', 'km²'],
                ['H_{śr,i}', 'średnia wysokość komórek NMT tej zlewni cząstkowej', 'm n.p.m.'],
            ],
            unit: 'm n.p.m.',
            meaning: 'Metoda Giandottiego liczy deniwelację jako $H_{śr} - H_{min}$: niższa wysokość średnia wydłuża $T_c$. Od $H_{śr}$ zależy też całka hipsometryczna $HI$.',
        },
        mean_slope_m_per_m: {
            title: 'Średni spadek terenu',
            symbol: 'I_{śr}',
            definition: 'Średnie nachylenie stoków: spadki komórek NMT uśrednione w zlewniach cząstkowych, a następnie średnia ważona ich powierzchnią.',
            formula: f`I_{śr} = \frac{∑ A_i I_i}{∑ A_i}`,
            variables: [
                ['A_i', 'powierzchnia i-tej zlewni cząstkowej', 'km²'],
                ['I_i', 'średni spadek komórek NMT tej zlewni cząstkowej', '%'],
            ],
            unit: '%',
            meaning: 'Spadek stoków, nie cieku. Używają go metody Tc: NRCS, FAA, Kerby i część spływu po stoku w Kerby-Kirpich. Większy spadek skraca $T_c$, co w modelu SCS daje wcześniejszy i wyższy szczyt.',
        },
        channel_length_km: {
            title: 'Długość cieku głównego',
            symbol: 'L_g',
            definition: 'Ciek główny biegnie od ujścia w górę sieci cieków wyznaczonej z NMT, na każdym rozwidleniu w stronę dopływu o największej powierzchni zlewni. Jego długość to suma długości odcinków.',
            formula: 'L_g = ∑ l_j',
            variables: [['l_j', 'długość j-tego odcinka sieci na drodze cieku głównego', 'km']],
            unit: 'km',
            meaning: 'Używają jej metoda Giandottiego oraz modele Snydera i Nasha (Lutz); w Kerby-Kirpich – gdy odcinek przy ujściu nie jest ciekiem BDOT10k.',
            note: 'Sieć cieków z NMT zaczyna się tam, gdzie powierzchnia spływająca do danego miejsca przekracza próg akumulacji, więc ciek nie sięga działu wodnego, a jego długość zależy od progu sieci.',
        },
        real_channel_length_km: {
            title: 'Ciek główny zgodny z BDOT10k',
            symbol: 'L_{BDOT}',
            definition: 'Długość części cieku głównego od ujścia w górę, która pokrywa się z ciekami BDOT10k. Przerwy do dwóch odcinków są wliczane; liczenie kończy się na dłuższej przerwie.',
            unit: 'km',
            meaning: 'Metoda Kerby-Kirpich bierze ją jako długość koryta (część Kirpicha), a resztę najdłuższej drogi spływu traktuje jako spływ po stoku (część Kerby’ego). Jej udział w $L_g$ to „Pokrycie BDOT” w sekcji Sieć rzeczna.',
            note: 'Odcinek sieci z NMT uznaje się za ciek BDOT10k, gdy co najmniej 50% jego długości leży nie dalej niż 25 m od cieku BDOT10k. Wartość 0 – odcinek przy ujściu nie jest takim ciekiem.',
        },
        channel_slope_m_per_m: {
            title: 'Spadek cieku głównego',
            symbol: 'I_g',
            definition: 'Różnica wysokości wzdłuż cieku głównego podzielona przez jego długość.',
            formula: f`I_g = \frac{H_{max,g} - H_{min,u}}{1000 · L_g}`,
            variables: [
                ['H_{max,g}', 'najwyższa wysokość zlewni cząstkowej na górnym końcu cieku', 'm n.p.m.'],
                ['H_{min,u}', 'najniższa wysokość zlewni cząstkowej przy ujściu', 'm n.p.m.'],
                L_G,
            ],
            unit: 'm/m (w tabeli w %)',
            meaning: 'Używają go metoda Kirpicha, część korytowa Kerby-Kirpich i estymacja Nasha metodą Lutza. Większy spadek skraca $T_c$ (Kirpich) i czas do szczytu $t_p$ (Lutz).',
            note: 'Górna wysokość to najwyższy punkt całej zlewni cząstkowej, a nie koryta – przy krótkim cieku spadek bywa wyraźnie zawyżony.',
        },
        hydraulic_length_km: {
            title: 'Najdłuższa droga spływu',
            symbol: 'L_{max}',
            definition: 'Długość drogi spływu od najdalszej komórki NMT zlewni do ujścia, po kierunkach spływu z NMT.',
            formula: 'L_{max} = max_i d_i - d_u',
            variables: [
                ['d_i', 'najdłuższa droga spływu z i-tej zlewni cząstkowej do ujścia całego obszaru danych', 'km'],
                ['d_u', 'droga spływu z ujścia zlewni do ujścia obszaru danych', 'km'],
            ],
            unit: 'km',
            meaning: 'Metody NRCS i Kirpicha używają jej jako długości – dłuższa droga wydłuża $T_c$. W Kerby-Kirpich przy pustym polu „L spływu” spływ po stoku ma długość $L_{max}$ minus długość koryta.',
        },
        divide_flow_path_km: {
            title: 'Droga spływu z działu wodnego',
            symbol: 'L_{dz}',
            definition: 'Najdłuższa droga spływu z punktu na granicy zlewni do ujścia, odczytana z rastra odległości spływu w wierzchołkach granicy.',
            formula: 'L_{dz} = max_k d_k - d_u',
            variables: [
                ['d_k', 'droga spływu z k-tego wierzchołka granicy do ujścia obszaru danych', 'km'],
                ['d_u', 'droga spływu z ujścia zlewni do ujścia obszaru danych', 'km'],
            ],
            unit: 'km',
            meaning: 'Wartość informacyjna – nie wpływa na $T_c$ ani na hydrogram.',
            note: 'Granica jest wygładzona, więc jej wierzchołki mogą leżeć w komórkach odwadnianych inną drogą; wtedy wynik przekracza najdłuższą drogę spływu i nie opisuje tej zlewni.',
        },
        cn: {
            title: 'Parametr CN (krzywa odpływu)',
            symbol: 'CN',
            definition: 'Parametr metody SCS-CN (0–100) opisujący, jak zlewnia zatrzymuje opad: średnia ważona powierzchnią z wartości CN przypisanych klasom pokrycia terenu BDOT10k (wartości dla przeciętnej wilgotności, AMC II).',
            formula: f`CN = \frac{∑ A_j CN_j}{∑ A_j}`,
            variables: [
                ['A_j', 'powierzchnia j-tej klasy pokrycia terenu w zlewni', 'm²'],
                ['CN_j', 'CN tej klasy', '–'],
            ],
            unit: '–',
            meaning: 'Wyznacza retencję $S = 25400/CN - 254$ i straty początkowe $I_a = 0,2·S$, a przez nie opad efektywny: wyższy CN – mniejsze straty i większy odpływ. W metodzie NRCS wpływa też na $T_c$. Do hydrogramu CN jest przeliczany według wybranego uwilgotnienia początkowego (AMC).',
            note: 'Bez danych o pokryciu terenu hydrogram jest liczony z CN = 75.',
        },
        latitude: {
            title: 'Szerokość geograficzna ujścia',
            symbol: 'φ',
            definition: 'Położenie ujścia zlewni w układzie WGS84, przeliczone z układu PL-1992. Ujście to dolny koniec klikniętego odcinka cieku, dosunięty do granicy zlewni, gdy leży poza nią.',
            unit: '°N',
            meaning: 'Lokalizuje ujście – nie wchodzi do obliczeń. Opad PMAXTP jest interpolowany w klikniętym punkcie, nie w ujściu.',
        },
        longitude: {
            title: 'Długość geograficzna ujścia',
            symbol: 'λ',
            definition: 'Położenie ujścia zlewni w układzie WGS84, przeliczone z układu PL-1992. Ujście to dolny koniec klikniętego odcinka cieku, dosunięty do granicy zlewni, gdy leży poza nią.',
            unit: '°E',
            meaning: 'Lokalizuje ujście – nie wchodzi do obliczeń. Opad PMAXTP jest interpolowany w klikniętym punkcie, nie w ujściu.',
        },
        elevation_m: {
            title: 'Wysokość ujścia',
            symbol: 'H_u',
            definition: 'Wysokość przyjęta dla ujścia: najniższa wysokość terenu w zlewni według NMT ($H_{min}$), a nie odczyt w punkcie ujścia.',
            unit: 'm n.p.m.',
            meaning: 'Ta sama wartość co „Wysokość min.” – punkt odniesienia deniwelacji zlewni.',
        },

        // ── Wskaźniki kształtu ─────────────────────────────────────────
        compactness_coefficient: {
            title: 'Wskaźnik zwartości Graveliusa',
            symbol: 'C_z',
            definition: 'Stosunek obwodu zlewni do obwodu koła o tej samej powierzchni.',
            formula: f`C_z = \frac{P}{2 \sqrt{π A}}`,
            variables: [P, A],
            unit: '–',
            meaning: 'Dla koła $C_z = 1$, dla kwadratu ≈ 1,13; im większy, tym zlewnia mniej zwarta – wydłużona lub o poszarpanej granicy. Wskaźnik opisowy – nie wpływa na hydrogram.',
            note: 'Z definicji $C_z ≥ 1$. Wartość poniżej 1 oznacza niespójność danych: $A$ to suma komórek NMT, a $P$ – długość wygładzonej granicy; zdarza się w bardzo małych zlewniach.',
        },
        circularity_ratio: {
            title: 'Wskaźnik kolistości Millera',
            symbol: 'C_k',
            definition: 'Stosunek powierzchni zlewni do powierzchni koła o tym samym obwodzie.',
            formula: f`C_k = \frac{4 π A}{P^2}`,
            variables: [A, P],
            unit: '–',
            meaning: 'Dla koła $C_k = 1$, dla kwadratu ≈ 0,785; mniejsze wartości – zlewnia mniej zwarta. Jest odwrotnością kwadratu $C_z$. Wskaźnik opisowy.',
            note: 'Z definicji $C_k ≤ 1$. Wartość powyżej 1 nie opisuje kształtu, tylko niespójność $A$ (suma komórek NMT) i $P$ (wygładzona granica), widoczną w bardzo małych zlewniach.',
        },
        elongation_ratio: {
            title: 'Wskaźnik wydłużenia Schumma',
            symbol: 'C_w',
            definition: 'Stosunek średnicy koła o powierzchni zlewni do długości zlewni.',
            formula: f`C_w = \frac{2}{L} \sqrt{\frac{A}{π}}`,
            variables: [A, L],
            unit: '–',
            meaning: 'Dla koła ($L$ równe średnicy) $C_w = 1$; im mniejszy, tym zlewnia bardziej wydłużona. Wskaźnik opisowy.',
            note: '$L$ to najdłuższa droga spływu, a nie odcinek prosty – kręta droga spływu dodatkowo obniża $C_w$.',
        },
        form_factor: {
            title: 'Wskaźnik formy Hortona',
            symbol: 'C_f',
            definition: 'Stosunek powierzchni zlewni do kwadratu jej długości.',
            formula: f`C_f = \frac{A}{L^2}`,
            variables: [A, L],
            unit: '–',
            meaning: 'Dla koła ($L$ równe średnicy) $C_f = π/4 ≈ 0,785$; mniejsze wartości – zlewnia wydłużona. Wskaźnik opisowy.',
            note: '$L$ to najdłuższa droga spływu – kręta droga spływu obniża $C_f$.',
        },
        lemniscate_ratio: {
            title: 'Wskaźnik lemniskaty Chorleya',
            symbol: 'C_l',
            definition: 'Stosunek powierzchni koła o średnicy równej długości zlewni do powierzchni zlewni (z porównania kształtu zlewni z lemniskatą).',
            formula: f`C_l = \frac{π L^2}{4 A}`,
            variables: [L, A],
            unit: '–',
            meaning: 'Dla koła $C_l = 1$; im większy, tym zlewnia bardziej wydłużona. Zależy tylko od $C_f$: $C_l = π/(4 C_f)$. Wskaźnik opisowy.',
            note: '$L$ to najdłuższa droga spływu – kręta droga spływu podwyższa $C_l$.',
        },

        // ── Rzeźba terenu ──────────────────────────────────────────────
        relief_ratio: {
            title: 'Wskaźnik rzeźby',
            symbol: 'R',
            definition: 'Deniwelacja zlewni odniesiona do pierwiastka z jej powierzchni, czyli do boku kwadratu o tej samej powierzchni.',
            formula: f`R = \frac{H_{max} - H_{min}}{\sqrt{A}}`,
            variables: [H_MAX, H_MIN, A],
            unit: '‰ (m/km)',
            meaning: 'Pozwala porównywać rzeźbę zlewni różnej wielkości: większy $R$ – teren bardziej stromy i urozmaicony. Wskaźnik opisowy – nie wpływa na $T_c$ ani na hydrogram.',
        },
        divide_slope: {
            title: 'Spadek działu wodnego',
            symbol: 'R_p',
            definition: 'Deniwelacja zlewni odniesiona do długości jej granicy (obwodu).',
            formula: f`R_p = \frac{H_{max} - H_{min}}{P}`,
            variables: [H_MAX, H_MIN, P],
            unit: '‰ (m/km)',
            meaning: 'Deniwelacja przypadająca na kilometr działu wodnego. Wskaźnik opisowy – nie wpływa na hydrogram.',
            note: 'Zależy od obwodu, który skraca wygładzenie granicy.',
        },
        asymmetry_coefficient: {
            title: 'Współczynnik asymetrii',
            symbol: 'α',
            definition: 'Różnica powierzchni lewej i prawej części zlewni, rozdzielonych ciekiem głównym, odniesiona do powierzchni zlewni.',
            formula: f`α = \frac{2 (A_L - A_P)}{A}`,
            variables: [
                ['A_L', 'powierzchnia części lewobrzeżnej', 'km²'],
                ['A_P', 'powierzchnia części prawobrzeżnej', 'km²'],
                A,
            ],
            unit: '–',
            meaning: '0 – zlewnia symetryczna względem cieku głównego; wartość dodatnia – przewaga części lewobrzeżnej, ujemna – prawobrzeżnej. Wskaźnik opisowy.',
        },
        hypsometric_integral: {
            title: 'Całka hipsometryczna',
            symbol: 'HI',
            definition: 'Odpowiada polu pod krzywą hipsometryczną (wykres powyżej); Hydrograf liczy ją jako względne położenie średniej wysokości zlewni między wysokością minimalną a maksymalną.',
            formula: f`HI = \frac{H_{śr} - H_{min}}{H_{max} - H_{min}}`,
            variables: [H_MEAN, H_MIN, H_MAX],
            unit: '–',
            meaning: 'Bliska 1 – większość powierzchni leży wysoko, bliska 0 – większość leży nisko, w pobliżu ujścia. Licznik $H_{śr} - H_{min}$ to deniwelacja w metodzie Giandottiego. Sam wskaźnik nie wpływa na hydrogram.',
        },

        // ── Sieć rzeczna ───────────────────────────────────────────────
        drainage_density_km_per_km2: {
            title: 'Gęstość sieci rzecznej',
            symbol: 'D_d',
            definition: 'Łączna długość cieków na jednostkę powierzchni zlewni. Liczone są tylko odcinki sieci z NMT zgodne z ciekami BDOT10k.',
            formula: f`D_d = \frac{∑ l_j}{A}`,
            variables: [['l_j', 'długość j-tego odcinka sieci zgodnego z BDOT10k', 'km'], A],
            unit: 'km/km²',
            meaning: 'Gęstsza sieć oznacza krótszą drogę wody po stokach do koryta. Wskaźnik opisowy – nie wpływa na hydrogram; wchodzi do liczby chropowatości $R_n$.',
            note: 'Odcinek jest zgodny z BDOT10k, gdy co najmniej 50% jego długości leży nie dalej niż 25 m od cieku BDOT10k; 0 – brak takich odcinków. Wynik zależy od progu sieci cieków.',
        },
        stream_frequency_per_km2: {
            title: 'Częstość cieków',
            symbol: 'F_s',
            definition: 'Liczba odcinków cieków na jednostkę powierzchni zlewni; liczone są odcinki sieci z NMT zgodne z BDOT10k.',
            formula: f`F_s = \frac{N}{A}`,
            variables: [['N', 'liczba odcinków zgodnych z BDOT10k; odcinek kończy się na połączeniu cieków lub zmianie rzędu', '–'], A],
            unit: '1/km²',
            meaning: 'Opisuje rozczłonkowanie sieci. Liczba odcinków zależy od progu sieci, więc zlewnie warto porównywać przy tym samym progu. Wskaźnik opisowy.',
        },
        ruggedness_number: {
            title: 'Liczba chropowatości',
            symbol: 'R_n',
            definition: 'Iloczyn gęstości sieci rzecznej i deniwelacji zlewni wyrażonej w kilometrach.',
            formula: f`R_n = D_d · \frac{H_{max} - H_{min}}{1000}`,
            variables: [['D_d', 'gęstość sieci rzecznej', 'km/km²'], H_MAX, H_MIN],
            unit: '–',
            meaning: 'Duża wartość – zlewnia jednocześnie stroma i gęsto pocięta ciekami. Wskaźnik opisowy – nie wpływa na hydrogram.',
        },
        max_strahler_order: {
            title: 'Maksymalny rząd cieku wg Strahlera',
            definition: 'Najwyższy rząd wśród odcinków sieci zgodnych z BDOT10k. Odcinki źródłowe mają rząd 1; połączenie dwóch cieków rzędu $n$ daje rząd $n + 1$, a połączenie cieków różnych rzędów zachowuje wyższy.',
            unit: '–',
            meaning: 'Opisuje rozbudowanie sieci rzecznej. Rząd jest liczony w sieci z NMT przy bieżącym progu – gęstsza sieć (niższy próg) daje wyższe rzędy. Wskaźnik opisowy.',
            note: 'Brak wartości – w zlewni nie ma odcinków zgodnych z BDOT10k.',
        },
        bdot_coverage: {
            title: 'Pokrycie cieku głównego przez BDOT10k',
            symbol: 'p_{BDOT}',
            definition: 'Udział cieku głównego (liczonego od ujścia) pokrytego ciekami BDOT10k.',
            formula: f`p_{BDOT} = 100 · \frac{L_{BDOT}}{L_g}`,
            variables: [['L_{BDOT}', 'część cieku głównego zgodna z BDOT10k', 'km'], L_G],
            unit: '%',
            meaning: 'Pokazuje, jaka część cieku głównego z NMT ma odpowiednik w BDOT10k. W metodzie Kerby-Kirpich ta część jest korytem (Kirpich), a reszta drogi spływu – spływem po stoku (Kerby).',
        },

        // ── Hietogram: formularz ───────────────────────────────────────
        'hydro-duration': {
            title: 'Czas trwania opadu',
            symbol: 'D',
            definition: 'Czas trwania opadu projektowego. Wysokość opadu $P$ dla wybranych $D$ i $p$ pochodzi z atlasu PMAXTP (IMGW-PIB), interpolowana w klikniętym punkcie z 4 najbliższych węzłów siatki metodą odwrotnych odległości (IDW).',
            formula: f`P = \frac{∑ P_i / d_i^2}{∑ 1 / d_i^2}`,
            variables: [
                ['P_i', 'opad PMAXTP w i-tym węźle siatki', 'mm'],
                ['d_i', 'odległość węzła od klikniętego punktu', 'm'],
            ],
            unit: 'min lub h (od 5 min do 72 h)',
            meaning: 'Hietogram dzieli opad na $n = D/Δt$ kroków po 5 min. Dłuższy opad ma większą sumę, ale mniejsze średnie natężenie; $Q_{max}$ zależy od obu, dlatego warto porównać kilka czasów trwania.',
        },
        'hydro-probability': {
            title: 'Prawdopodobieństwo przewyższenia',
            symbol: 'p',
            definition: 'Prawdopodobieństwo, że w danym roku opad o czasie trwania $D$ osiągnie lub przekroczy wysokość $P$. Odpowiada mu okres powtarzalności $T$.',
            formula: f`T = \frac{100}{p}`,
            variables: [
                ['p', 'prawdopodobieństwo przewyższenia', '%'],
                ['T', 'okres powtarzalności', 'lata'],
            ],
            unit: '%',
            meaning: 'Mniejsze $p$ – rzadszy i wyższy opad, a więc większy odpływ; np. $p = 1 %$ odpowiada $T = 100$ lat.',
        },
        'hydro-hietogram-type': {
            title: 'Rozkład opadu w czasie (hietogram)',
            definition: 'Sposób rozłożenia sumy opadu $P$ na $n$ kroków $Δt$ = 5 min w czasie trwania $D$.',
            formula: f`P_i = P · \frac{w_i}{∑ w_j}`,
            variables: [
                ['P_i', 'opad w i-tym kroku', 'mm'],
                ['w_i', 'waga kroku według rozkładu', '–'],
            ],
            unit: 'mm w kroku',
            list: {
                title: 'Rozkłady',
                items: [
                    ['Beta', 'kształt według $α$ i $β$: $w_i = t_i^{α-1} (1 - t_i)^{β-1}$, gdzie $t_i = (i - 0,5)/n$'],
                    ['DVWK (Euler II)', 'największy blok w 1/3 czasu trwania, kolejne – malejąco jak $w_r = r^{-0,7}$ ($r$ – ranga) – naprzemiennie przed nim i po nim'],
                    ['Blokowy', 'stałe natężenie, $w_i = 1$'],
                ],
            },
            meaning: 'Opad efektywny liczy się od sumy narastającej, więc ten sam blok opadu daje więcej odpływu, gdy spada później (straty $I_a$ są już pokryte). Przy tej samej sumie $P$ rozkład zmienia więc szczyt i czas szczytu hydrogramu.',
            note: 'Rozkład DVWK w Hydrologu jest przybliżeniem: wagi bloków nie pochodzą z lokalnych krzywych natężenie–czas trwania, tylko z zaniku $r^{-0,7}$. Przy własnej serii opadu rozkład nie jest używany.',
        },
        'hydro-alpha': {
            title: 'Parametr α rozkładu Beta',
            symbol: 'α',
            definition: 'Parametr kształtu rozkładu Beta; razem z $β$ ustala, kiedy w czasie trwania wypada szczyt opadu.',
            formula: BETA_PEAK.formula,
            variables: BETA_PEAK.variables,
            unit: '–',
            meaning: 'Przy $α = β$ opad jest symetryczny; $α < β$ przesuwa szczyt na początek opadu, $α > β$ – na koniec. Domyślnie $α = 2$, $β = 5$: szczyt w 0,2 czasu trwania.',
            note: 'Dozwolony zakres: $0 < α ≤ 20$.',
        },
        'hydro-beta': {
            title: 'Parametr β rozkładu Beta',
            symbol: 'β',
            definition: 'Parametr kształtu rozkładu Beta; razem z $α$ ustala, kiedy w czasie trwania wypada szczyt opadu.',
            formula: BETA_PEAK.formula,
            variables: BETA_PEAK.variables,
            unit: '–',
            meaning: 'Większe $β$ przy tym samym $α$ przesuwa szczyt bliżej początku opadu. Przy $α = β$ opad jest symetryczny. Domyślnie $β = 5$.',
            note: 'Dozwolony zakres: $0 < β ≤ 20$.',
        },
        'hydro-amc': {
            title: 'Uwilgotnienie początkowe (AMC)',
            definition: 'Stan uwilgotnienia zlewni przed opadem wg SCS: I – suche, II – przeciętne (domyślnie), III – mokre. CN zlewni, podany dla AMC II, jest przeliczany:',
            formula: [
                f`CN_{\text{I}} = \frac{CN}{2,281 - 0,01281 · CN}`,
                f`CN_{\text{III}} = \frac{CN}{0,427 + 0,00573 · CN}`,
            ],
            variables: [['CN', 'CN zlewni dla AMC II', '–']],
            meaning: 'AMC III podnosi CN (mniejsza retencja, większy odpływ), AMC I go obniża; np. CN 78,3 daje 61 przy AMC I i 89 przy AMC III. Zmiana dotyczy strat i opadu efektywnego, a przez nie całego hydrogramu.',
            note: 'Przeliczony CN jest zaokrąglany do liczby całkowitej i ograniczany do 1–100 (Hydrolog, wzory wg Chow i in. 1988).',
        },
        'custom-rain': {
            title: 'Własna seria opadu',
            definition: 'Zamiast opadu PMAXTP i rozkładu można podać własny hietogram: wysokość opadu w każdym kroku czasowym o stałej długości $Δt$. Czas trwania $D$ musi być wielokrotnością kroku; tabela ma $n = D/Δt$ wierszy z czasem końca kroku i opadem.',
            formula: [f`n = \frac{D}{Δt}`, f`P = ∑_{i=1}^{n} P_i`],
            variables: [
                ['D', 'czas trwania opadu', 'min'],
                ['Δt', 'krok czasowy (większy od 0, najwyżej 1440)', 'min'],
                ['n', 'liczba kroków (od 1 do 2000)', '–'],
                ['P_i', 'opad w i-tym kroku (≥ 0)', 'mm'],
                ['P', 'suma opadu (większa od 0)', 'mm'],
            ],
            list: {
                title: 'Plik CSV',
                items: [
                    ['1 kolumna', 'opad [mm] w kolejnych krokach, z bieżącym krokiem $Δt$'],
                    ['2 kolumny', 'czas [min] (koniec kroku albo 0 na początku) i opad [mm]; czasy w równych odstępach wyznaczają krok'],
                    ['Separator', 'przecinek, średnik lub tabulator; przecinek dziesiętny przy średniku lub tabulatorze; wiersz nagłówka jest pomijany'],
                ],
            },
            meaning: 'Seria zastępuje czas trwania, prawdopodobieństwo i rozkład opadu PMAXTP; hydrogram jest liczony z krokiem $Δt$ serii. Straty SCS-CN i przeliczenie AMC działają tak samo jak dla opadu PMAXTP.',
            note: 'Wartości to wysokości opadu w kroku [mm], a nie natężenia [mm/h]. „Wczytaj z bieżącego hietogramu” przenosi do tabeli ostatni hietogram PMAXTP.',
        },

        // ── Hietogram: wyniki ──────────────────────────────────────────
        total_precip_mm: {
            title: 'Opad całkowity',
            symbol: 'P',
            definition: 'Suma opadu we wszystkich krokach hietogramu: wysokość z PMAXTP albo suma własnej serii opadu.',
            formula: f`P = ∑_{i=1}^{n} P_i`,
            variables: [['P_i', 'opad w i-tym kroku', 'mm'], ['n', 'liczba kroków', '–']],
            unit: 'mm',
            meaning: 'Punkt wyjścia bilansu – z niego metodą SCS-CN liczony jest opad efektywny $P_e$.',
        },
        total_effective_mm: {
            title: 'Opad efektywny',
            symbol: 'P_e',
            definition: 'Część opadu, która odpływa po odjęciu strat (metoda SCS-CN). Liczony od sumy narastającej; przyrosty w kolejnych krokach tworzą hietogram opadu efektywnego.',
            formula: f`P_e = \frac{(P - I_a)^2}{P - I_a + S}`,
            variables: [['P', 'suma opadu', 'mm'], ['I_a', 'straty początkowe', 'mm'], S],
            unit: 'mm',
            meaning: 'Wejście hydrogramu jednostkowego: hydrogram to splot przyrostów $P_e$ z hydrogramem jednostkowym, a objętość odpływu $V ≈ P_e·A$.',
            note: 'Gdy $P ≤ I_a$, $P_e = 0$ – odpływu nie ma.',
        },
        runoff_coefficient: {
            title: 'Współczynnik odpływu',
            symbol: 'ψ',
            definition: 'Udział opadu efektywnego w opadzie całkowitym.',
            formula: f`ψ = \frac{P_e}{P}`,
            variables: [['P_e', 'opad efektywny', 'mm'], ['P', 'opad całkowity', 'mm']],
            unit: '–',
            meaning: 'Jaka część opadu odpływa: 0 – nic, 1 – całość. Rośnie z CN, z wysokością opadu i przy wilgotniejszych warunkach (AMC III).',
        },
        cn_used: {
            title: 'CN użyty w obliczeniu',
            symbol: 'CN',
            definition: 'Wartość CN, z której policzono straty: CN zlewni (AMC II) albo – przy AMC I lub III – wartość przeliczona i zaokrąglona do liczby całkowitej.',
            unit: '–',
            meaning: 'Od niego zależą retencja $S$ i straty początkowe $I_a$, a więc opad efektywny i cały hydrogram.',
            note: 'Gdy zlewnia nie ma CN z pokrycia terenu, użyto CN = 75.',
        },
        retention_mm: {
            title: 'Retencja maksymalna',
            symbol: 'S',
            definition: 'Największa ilość wody, jaką zlewnia może zatrzymać po rozpoczęciu odpływu (metoda SCS-CN).',
            formula: f`S = \frac{25400}{CN} - 254`,
            variables: [['CN', 'CN użyty w obliczeniu', '–']],
            unit: 'mm',
            meaning: 'Im większa, tym mniejszy opad efektywny. Dla $CN = 100$: $S = 0$ – cały opad odpływa.',
        },
        initial_abstraction_mm: {
            title: 'Straty początkowe',
            symbol: 'I_a',
            definition: 'Opad zatrzymany przed początkiem odpływu: intercepcja, retencja w zagłębieniach terenu i wsiąkanie.',
            formula: 'I_a = 0,2 · S',
            variables: [S],
            unit: 'mm',
            meaning: 'Dopóki suma opadu nie przekroczy $I_a$, odpływu nie ma – przy małym opadzie hydrogram może być zerowy.',
            note: 'Współczynnik 0,2 to standard SCS (NEH 630); proponowanej wartości 0,05 Hydrograf nie stosuje.',
        },

        // ── Hydrogram: formularz ───────────────────────────────────────
        'hydro-uh-model': {
            title: 'Model hydrogramu jednostkowego',
            definition: 'Hydrogram jednostkowy to odpowiedź zlewni na 1 mm opadu efektywnego w jednym kroku $Δt$; hydrogram odpływu jest splotem przyrostów opadu efektywnego z hydrogramem jednostkowym (wzór przy wyniku „Hydrogram jedn.”).',
            meaning: 'Model ustala kształt odpowiedzi zlewni – czas do szczytu i wysokość szczytu; objętość odpływu zależy od $P_e$ i $A$, a nie od modelu.',
        },
        'hydro-tc-method': {
            title: 'Czas koncentracji',
            symbol: 'T_c',
            definition: 'Czas dopływu wody z hydraulicznie najdalszego punktu zlewni do ujścia.',
            unit: 'min',
            meaning: 'W modelu SCS wyznacza opóźnienie $t_{lag} = 0,6·T_c$: krótszy $T_c$ – wcześniejszy i wyższy szczyt. W Nashu „z Tc” daje $K = 0,6·T_c/N$. W modelu Snydera $T_c$ nie zmienia hydrogramu, a przy estymacji Nasha metodą Lutza lub regresji nie jest liczony.',
            note: 'Metody mogą dawać dla tej samej zlewni $T_c$ różniące się kilkukrotnie – sprawdź zakres stosowalności wybranej metody.',
        },
        'hydro-tc-runoff-coeff': {
            title: 'Współczynnik spływu (FAA)',
            symbol: 'C',
            definition: 'Współczynnik spływu metody racjonalnej, używany tylko w metodzie FAA.',
            formula: f`C = 1 - \frac{S}{S + 25,4}`,
            variables: [S],
            unit: '–',
            meaning: 'Większy $C$ (powierzchnia mniej przepuszczalna) skraca $T_c$ przez czynnik $1,1 - C$.',
            note: 'Puste pole – $C$ liczony z CN zlewni wzorem powyżej (dla $CN = 100$: $C = 0,95$). Typowy zakres metody 0,10–0,95.',
        },
        'hydro-tc-retardance': {
            title: 'Współczynnik oporu (Kerby)',
            symbol: 'N',
            definition: 'Szorstkość powierzchni spływu w metodach Kerby i Kerby-Kirpich (domyślnie 0,4).',
            unit: '–',
            list: {
                title: 'Typowe wartości',
                items: [
                    ['0,02', 'gładkie powierzchnie nieprzepuszczalne (asfalt, beton)'],
                    ['0,10', 'gładka, ubita, odkryta gleba'],
                    ['0,20', 'słaba trawa, uprawy rzędowe'],
                    ['0,40', 'pastwisko, przeciętna trawa'],
                    ['0,60', 'las liściasty'],
                    ['0,80', 'gęsta trawa, las iglasty, las liściasty ze ściółką'],
                ],
            },
            meaning: '$T_c$ rośnie z $N$ w potędze 0,467 – bardziej szorstka powierzchnia spowalnia spływ.',
        },
        'hydro-tc-overland-length': {
            title: 'Długość spływu powierzchniowego',
            symbol: 'L_{sp}',
            definition: 'Długość spływu po powierzchni (warstwowego) od działu wodnego do początku wyraźnego koryta.',
            unit: 'km',
            meaning: 'Wymagana w metodach FAA (typowo 0,015–3 km) i Kerby (0,01–0,366 km). W Kerby-Kirpich puste pole oznacza $L_{sp} = L_{max} - L_k$, co najmniej 0,1 km.',
            note: 'To nie jest długość zlewni – podaj tylko odcinek spływu po stoku.',
        },
        'hydro-nash-estimation': {
            title: 'Estymacja parametrów Nasha',
            definition: 'Sposób wyznaczenia liczby zbiorników $N$ i stałej retencji $K$ kaskady Nasha.',
            meaning: 'Metody dają różne $N$ i $K$, a więc różne $Q_{max}$ i czas do szczytu – warto je porównać.',
        },
        'hydro-nash-n': {
            title: 'Liczba zbiorników',
            symbol: 'N',
            definition: 'Liczba zbiorników kaskady Nasha w estymacji „z Tc” (domyślnie 3).',
            formula: f`K = \frac{0,6 · T_c}{N}`,
            variables: [TC],
            unit: '–',
            meaning: 'Przy stałym opóźnieniu $N·K = 0,6·T_c$ większe $N$ daje szczyt później ($t_p = (N - 1)·K$) i wyższy, bo hydrogram jest mniej rozciągnięty (wariancja $N·K^2$ maleje).',
        },
        'hydro-snyder-ct': {
            title: 'Współczynnik czasu (Snyder)',
            symbol: 'C_t',
            definition: 'Współczynnik opóźnienia w modelu Snydera (domyślnie 1,5).',
            formula: f`t_L = C_t (L_g L_c)^{0,3}`,
            variables: [L_G, L_C, ['t_L', 'opóźnienie zlewni', 'h']],
            unit: '–',
            meaning: 'Większy $C_t$ – dłuższe opóźnienie, szczyt później i niższy ($q_p$ jest odwrotnie proporcjonalny do $t_L$).',
            note: 'Typowo 1,35–1,65 (SI): mniejsze dla zlewni stromych, górskich, większe dla płaskich, podmokłych.',
        },
        'hydro-snyder-cp': {
            title: 'Współczynnik szczytu (Snyder)',
            symbol: 'C_p',
            definition: 'Współczynnik przepływu szczytowego w modelu Snydera (domyślnie 0,6).',
            formula: f`q_p = 0,275 · C_p \frac{A}{t_L}`,
            variables: [A, ['t_L', 'opóźnienie zlewni', 'h'], ['q_p', 'przepływ szczytowy hydrogramu jednostkowego', 'm³/s na 1 mm']],
            unit: '–',
            meaning: 'Proporcjonalnie podnosi szczyt hydrogramu jednostkowego; jego objętość jest normowana do 1 mm, więc wyższy szczyt oznacza węższy hydrogram.',
            note: 'Typowo 0,4–0,8: mniejsze przy dużej retencji (zlewnie wiejskie), większe przy małej (miejskie).',
        },

        // ── Hydrogram: wyniki ──────────────────────────────────────────
        peak_discharge_m3s: {
            title: 'Przepływ maksymalny',
            symbol: 'Q_{max}',
            definition: 'Największa rzędna hydrogramu odpływu w ujściu.',
            formula: 'Q_{max} = max_k Q_k',
            variables: [['Q_k', 'przepływ w k-tym kroku hydrogramu', 'm³/s']],
            unit: 'm³/s',
            meaning: 'Główny wynik projektowy. Rośnie z opadem efektywnym i powierzchnią, maleje przy dłuższym czasie reakcji zlewni ($T_c$, $N·K$, $t_L$).',
            note: 'To odpływ bezpośredni z opadu – bez przepływu bazowego.',
        },
        time_to_peak_min: {
            title: 'Czas do szczytu',
            symbol: 't_p',
            definition: 'Czas od początku opadu do wystąpienia $Q_{max}$.',
            unit: 'min',
            meaning: 'Mówi, jak szybko po rozpoczęciu opadu nadchodzi szczyt; zależy od rozkładu opadu i od parametrów czasowych modelu ($T_c$, $N·K$, $t_L$).',
            note: 'Odczyt z siatki czasu hydrogramu – z dokładnością do kroku $Δt$.',
        },
        total_volume_m3: {
            title: 'Objętość odpływu',
            symbol: 'V',
            definition: 'Objętość wody odpływającej w czasie całego hydrogramu: pole pod hydrogramem.',
            formula: 'V = ∑_k Q_k · 60 Δt',
            variables: [['Q_k', 'przepływ w k-tym kroku', 'm³/s'], DT],
            unit: 'm³',
            meaning: 'Odpowiada w przybliżeniu $P_e·A$ (1 mm z 1 km² to 1000 m³); zależy od opadu efektywnego, a nie od modelu hydrogramu.',
        },
        tc_method: {
            title: 'Metoda czasu koncentracji',
            definition: 'Metoda, którą policzono $T_c$ (wybór w polu „Metoda Tc”).',
            meaning: 'Wpływa na hydrogram w modelu SCS i w Nashu „z Tc”; w modelu Snydera $T_c$ jest tylko informacyjny.',
        },
        tc_min: {
            title: 'Czas koncentracji',
            symbol: 'T_c',
            definition: 'Czas dopływu wody z hydraulicznie najdalszego punktu zlewni do ujścia, policzony wybraną metodą.',
            formula: 't_{lag} = 0,6 · T_c',
            variables: [['t_{lag}', 'opóźnienie zlewni w modelu SCS', 'min']],
            unit: 'min',
            meaning: 'W modelu SCS krótszy $T_c$ – wcześniejszy i wyższy szczyt; w Nashu „z Tc” wyznacza $K$. W modelu Snydera nie zmienia hydrogramu.',
        },
        uh_model: {
            title: 'Model hydrogramu jednostkowego',
            definition: 'Model użyty w obliczeniu (dla Nasha w nawiasie sposób estymacji $N$ i $K$). Hydrogram odpływu jest splotem przyrostów opadu efektywnego z hydrogramem jednostkowym $u$ – odpowiedzią zlewni na 1 mm opadu efektywnego w jednym kroku:',
            formula: 'Q_k = ∑_i P_{e,i} · u_{k-i}',
            variables: [
                ['Q_k', 'przepływ w chwili $k·Δt$ od początku opadu', 'm³/s'],
                ['P_{e,i}', 'opad efektywny w i-tym kroku', 'mm'],
                ['u_j', 'rzędna hydrogramu jednostkowego po $j$ krokach', 'm³/s na 1 mm'],
            ],
            meaning: 'Model ustala kształt hydrogramu (czas do szczytu, wysokość szczytu); objętość odpływu zależy od opadu efektywnego i powierzchni.',
        },
        nash_n: {
            title: 'Liczba zbiorników kaskady Nasha',
            symbol: 'N',
            definition: 'Liczba jednakowych zbiorników liniowych w kaskadzie Nasha.',
            formula: ['t_{lag} = N · K', 't_p = (N - 1) · K'],
            variables: [['K', 'stała retencji zbiornika', 'min'], ['t_{lag}', 'opóźnienie (środek ciężkości hydrogramu chwilowego)', 'min'], ['t_p', 'czas do szczytu hydrogramu chwilowego', 'min']],
            unit: '–',
            meaning: 'Razem z $K$ ustala opóźnienie i kształt hydrogramu: większe $N$ – szczyt później.',
        },
        nash_k_min: {
            title: 'Stała retencji zbiornika',
            symbol: 'K',
            definition: 'Stała retencji każdego zbiornika kaskady Nasha.',
            formula: f`u(t) = \frac{1}{K Γ(N)} (\frac{t}{K})^{N-1} e^{-t/K}`,
            variables: [['u(t)', 'rzędna hydrogramu chwilowego', '1/min'], ['N', 'liczba zbiorników', '–'], ['Γ', 'funkcja gamma', ''], ['t', 'czas od opadu', 'min']],
            unit: 'min',
            meaning: 'Większe $K$ – hydrogram bardziej opóźniony i spłaszczony (opóźnienie $N·K$, szczyt maleje jak $1/K$).',
        },
        nash_urban_fraction: {
            title: 'Wskaźnik urbanizacji',
            symbol: 'U',
            definition: 'Średnia ważona powierzchnią nieprzepuszczalność pokrycia terenu zlewni (klasy BDOT10k), użyta jako $U$ w regresji urbanizacyjnej; pokazana w %.',
            formula: f`U = \frac{∑ A_j u_j}{∑ A_j}`,
            variables: [['A_j', 'powierzchnia j-tej klasy pokrycia terenu', 'm²'], ['u_j', 'nieprzepuszczalność tej klasy', '–']],
            unit: '– (w tabeli w %)',
            meaning: 'Większe $U$ skraca opóźnienie ($t_L ∝ (1 + U)^{-1,66}$) i stałą $k ∝ (1 + U)^{-0,62}$ – hydrogram szybszy i wyższy.',
        },
        nash_effective_precip_mm: {
            title: 'Opad efektywny w regresji Nasha',
            symbol: 'H',
            definition: 'Opad efektywny SCS-CN policzony z całej sumy opadu, użyty jako $H$ w regresji urbanizacyjnej.',
            formula: f`H = \frac{(P - I_a)^2}{P - I_a + S}`,
            variables: [['P', 'suma opadu', 'mm'], ['I_a', 'straty początkowe', 'mm'], S],
            unit: 'mm',
            meaning: 'Większy opad efektywny skraca opóźnienie ($t_L ∝ H^{-0,27}$) – parametry Nasha zależą tu od samego opadu.',
        },
        nash_duration_h: {
            title: 'Czas trwania opadu efektywnego',
            symbol: 'D',
            definition: 'Czas, w którym przyrost opadu efektywnego jest dodatni: liczba takich kroków hietogramu razy krok $Δt$.',
            formula: 'D = n_e · Δt',
            variables: [['n_e', 'liczba kroków z dodatnim opadem efektywnym', '–'], DT],
            unit: 'h (pokazany też w min)',
            meaning: 'Dłuższy opad efektywny wydłuża opóźnienie ($t_L ∝ D^{0,37}$) i stałą $k ∝ D^{0,22}$.',
        },

        // ── Zakres stosowalności: modele UH ────────────────────────────
        'hydro-uh-model:scs': {
            summary: 'Ogólnego zastosowania (TR-55); Hydrolog nie ogranicza powierzchni ani $T_c$.',
            title: 'SCS (NRCS) – bezwymiarowy hydrogram jednostkowy',
            definition: 'Kształt z tablicy NRCS ($q/q_p$ od $t/t_p$, do $5 t_p$), skalowany czasem do szczytu $t_p$ i przepływem szczytowym $q_p$.',
            formula: [f`t_{lag} = 0,6 · T_c`, f`t_p = \frac{Δt}{2} + t_{lag}`, f`q_p = 0,208 · \frac{A}{t_p}`],
            variables: [
                TC, DT, A,
                ['t_p', 'czas do szczytu hydrogramu jednostkowego (we wzorze na $q_p$ w godzinach)', 'min'],
                ['q_p', 'przepływ szczytowy hydrogramu jednostkowego', 'm³/s na 1 mm'],
            ],
            meaning: 'Jedynym parametrem czasowym jest $T_c$: krótszy $T_c$ – wcześniejszy i wyższy szczyt, więc wybór metody Tc bezpośrednio zmienia $Q_{max}$.',
            range: 'USDA-NRCS TR-55 (1986). Hydrolog nie sprawdza zakresu powierzchni ani $T_c$; Hydrograf liczy hydrogram dla zlewni do 250 km².',
        },
        'hydro-uh-model:nash': {
            summary: 'Kaskada $N$ zbiorników liniowych; zakres zależy od sposobu estymacji $N$ i $K$.',
            title: 'Nash – kaskada zbiorników liniowych',
            definition: 'Zlewnia jako $N$ jednakowych zbiorników liniowych połączonych szeregowo, każdy o stałej retencji $K$. Hydrogram chwilowy:',
            formula: [f`u(t) = \frac{1}{K Γ(N)} (\frac{t}{K})^{N-1} e^{-t/K}`, 't_{lag} = N · K', 't_p = (N - 1) · K'],
            variables: [
                ['N', 'liczba zbiorników', '–'],
                ['K', 'stała retencji zbiornika', 'min'],
                ['Γ', 'funkcja gamma', ''],
                ['t_{lag}', 'opóźnienie (środek ciężkości hydrogramu chwilowego)', 'min'],
                ['t_p', 'czas do szczytu hydrogramu chwilowego', 'min'],
            ],
            meaning: 'Większe $K$ i $N$ – hydrogram bardziej opóźniony i spłaszczony. Hydrogram jednostkowy dla kroku $Δt$ powstaje z krzywej S hydrogramu chwilowego i jest skalowany powierzchnią $A$.',
            range: 'Hydrolog nie sprawdza zakresu; typowo $N$ = 1–10, $K$ = 10–200 min. Stosowalność zależy od wybranej estymacji $N$ i $K$.',
        },
        'hydro-uh-model:snyder': {
            summary: 'Hydrogram syntetyczny; $C_t$ 1,35–1,65, $C_p$ 0,4–0,8; Hydrolog nie sprawdza zakresu.',
            title: 'Snyder – syntetyczny hydrogram jednostkowy',
            definition: 'Hydrogram z empirycznych zależności od długości cieku i położenia środka ciężkości zlewni (Snyder 1938). Opóźnienie i szczyt są korygowane do kroku $Δt$:',
            formula: [
                f`t_L = C_t (L_g L_c)^{0,3}`,
                f`t_{LR} = t_L + 0,25 (Δt - \frac{t_L}{5,5})`,
                f`t_{pR} = t_{LR} + \frac{Δt}{2}`,
                f`q_{pR} = 0,275 · C_p \frac{A}{t_{LR}}`,
            ],
            variables: [
                ['C_t, C_p', 'współczynniki czasu i szczytu', '–'],
                L_G, L_C,
                ['Δt', 'krok czasowy', 'h'],
                ['t_L, t_{LR}', 'opóźnienie standardowe i skorygowane', 'h'],
                ['t_{pR}', 'czas do szczytu', 'h'],
                A,
                ['q_{pR}', 'przepływ szczytowy hydrogramu jednostkowego', 'm³/s na 1 mm'],
            ],
            meaning: 'Hydrogram zależy od $L_g$, $L_c$, $C_t$ i $C_p$; czas koncentracji $T_c$ jest pokazywany, ale nie zmienia hydrogramu Snydera. Objętość hydrogramu jednostkowego jest normowana do 1 mm.',
            range: 'Metoda empiryczna Snydera (1938), opracowana dla zlewni w USA; typowo $C_t$ = 1,35–1,65 (SI), $C_p$ = 0,4–0,8. Hydrolog nie sprawdza zakresu. Wymaga $L_g$ i $L_c$.',
        },

        // ── Zakres stosowalności: estymacja Nasha ──────────────────────
        'hydro-nash-estimation:from_lutz': {
            summary: 'Zalecana dla zlewni niezurbanizowanych bez pomiarów (Lutz 1984; KZGW 2017).',
            title: 'Metoda Lutza',
            definition: 'Parametry z cech fizjograficznych: najpierw czas do szczytu $t_p$ i rzędna szczytu $u_p$, z nich $N$, a potem $K$.',
            formula: [
                f`t_p = P_1 (\frac{L_g L_c}{I_g^{1,5}})^{0,26} e^{-0,016 U} e^{0,004 W}`,
                'P_1 = 3,989 n + 0,028',
                f`u_p = \frac{0,66}{t_p^{1,04}}`,
                f`t_p u_p = \frac{(N - 1)^N e^{-(N - 1)}}{Γ(N)}`,
                f`K = \frac{t_p}{N - 1}`,
            ],
            variables: [
                L_G, L_C,
                ['I_g', 'spadek cieku głównego', '–'],
                ['n', 'współczynnik szorstkości Manninga koryta', '–'],
                ['U, W', 'udział terenów zurbanizowanych i leśnych', '%'],
                ['t_p', 'czas do szczytu', 'h'],
                ['u_p', 'rzędna szczytu hydrogramu chwilowego', '1/h'],
            ],
            meaning: 'Większy spadek cieku skraca $t_p$ (szybsza reakcja), dłuższy ciek i dalszy środek ciężkości go wydłużają.',
            range: 'Zalecana dla zlewni niezurbanizowanych bez pomiarów. Wymaga $L_g$, $L_c$ i $I_g$ oraz $L_c ≤ L_g$; gdy $t_p u_p$ przekracza maksimum prawej strony równania na $N$, obliczenie kończy się błędem.',
            note: 'Hydrograf przyjmuje $n = 0,035$ oraz $U = W = 0$ – urbanizacja i lesistość nie są uwzględniane.',
        },
        'hydro-nash-estimation:from_urban_regression': {
            summary: 'Zlewnie zurbanizowane; regresja z ok. 200 opadów na zlewniach ok. 13–52 km² koło Indianapolis.',
            title: 'Regresja urbanizacyjna (Rao, Delleur, Sarma)',
            definition: 'Regresja dla zlewni zurbanizowanych i częściowo zurbanizowanych (Sarma i in. 1969, Rao i in. 1972).',
            formula: [
                f`t_L = 1,28 · A^{0,46} (1 + U)^{-1,66} H^{-0,27} D^{0,37}`,
                f`k = 0,56 · A^{0,39} (1 + U)^{-0,62} H^{-0,11} D^{0,22}`,
                f`N = \frac{t_L}{k}`,
            ],
            variables: [
                A,
                ['U', 'wskaźnik urbanizacji', '–'],
                ['H', 'opad efektywny', 'mm'],
                ['D', 'czas trwania opadu efektywnego', 'h'],
                ['t_L', 'opóźnienie', 'h'],
                ['k', 'stała retencji zbiornika ($K = 60 k$ min)', 'h'],
            ],
            meaning: 'Większa urbanizacja $U$ i większy opad efektywny $H$ skracają opóźnienie – hydrogram szybszy i wyższy.',
            range: 'Wyprowadzona z ok. 200 opadów na zlewniach 5–20 mi² (ok. 13–52 km²) koło Indianapolis. Hydrolog wymaga $0 ≤ U < 1$ i nie ostrzega poza zakresem kalibracji.',
            note: 'W Hydrografie $U$ to średnia ważona nieprzepuszczalność pokrycia terenu, $H$ – opad efektywny SCS-CN z sumy opadu, $D$ – liczba kroków z opadem efektywnym razy $Δt$.',
        },
        'hydro-nash-estimation:from_tc': {
            summary: 'Przestarzała: relacja SCS $t_{lag} = 0,6·T_c$ nie ma uzasadnienia dla modelu Nasha.',
            title: 'Z czasu koncentracji (przestarzała)',
            definition: 'Stała $K$ z czasu koncentracji przy zadanej liczbie zbiorników $N$.',
            formula: f`K = \frac{0,6 · T_c}{N}`,
            variables: [TC, ['N', 'liczba zbiorników (pole „N (zbiorniki)”)', '–']],
            unit: 'min',
            meaning: 'Opóźnienie kaskady $N·K$ jest wymuszone równe $0,6·T_c$, więc wynik zależy od metody Tc.',
            range: 'Oznaczona w Hydrologu jako przestarzała: zależność $t_{lag} = 0,6·T_c$ opracowano dla hydrogramu SCS, a w kaskadzie Nasha opóźnienie $N·K$ wynika z jej budowy. Lepiej użyć metody Lutza lub regresji.',
        },

        // ── Zakres stosowalności: metody Tc ────────────────────────────
        'hydro-tc-method:nrcs': {
            summary: 'L 0,03–30 km, spadek 0,1–15%, CN 50–95 (TR-55).',
            title: 'NRCS (SCS Lag)',
            definition: 'Opóźnienie zlewni wg NRCS (TR-55) przeliczone na czas koncentracji, $T_c = t_{lag}/0,6$; uwzględnia retencję zlewni przez CN.',
            formula: f`T_c = 0,01416 · L_{max}^{0,8} (S + 25,4)^{0,7} I_{śr}^{-0,5}`,
            variables: [
                ['L_{max}', 'najdłuższa droga spływu', 'm'],
                S,
                ['I_{śr}', 'średni spadek terenu', '%'],
            ],
            unit: 'min',
            meaning: 'Wyższy CN (mniejsza retencja) i większy spadek skracają $T_c$; dłuższa droga spływu go wydłuża.',
            range: 'Typowy zakres: $L$ 0,03–30 km, spadek 0,001–0,15 m/m, CN 50–95. Poza nim Hydrolog zgłasza ostrzeżenie, którego aplikacja nie pokazuje.',
        },
        'hydro-tc-method:kirpich': {
            summary: 'Małe zlewnie rolnicze (kalibracja 0,004–0,45 km²); L do 80 km, spadek 0,2–15%.',
            title: 'Kirpich (1940)',
            definition: 'Wzór empiryczny dla małych zlewni rolniczych.',
            formula: f`T_c = 3,981 · L_{max}^{0,77} · I_g^{-0,385}`,
            variables: [
                ['L_{max}', 'najdłuższa droga spływu', 'km'],
                ['I_g', 'spadek cieku głównego (gdy brak – średni spadek terenu)', 'm/m'],
            ],
            unit: 'min',
            meaning: 'Zależy tylko od długości i spadku – nie od CN ani pokrycia terenu.',
            range: 'Kalibracja: 7 małych zlewni rolniczych w Tennessee, 0,004–0,45 km², spadki 3–10%. Ostrzeżenie Hydrologu (aplikacja go nie pokazuje) poza: $L$ 0,001–80 km, spadek 0,002–0,15 m/m.',
        },
        'hydro-tc-method:giandotti': {
            summary: 'Duże zlewnie górskie (opracowana dla > 170 km²); ostrzeżenie dla A < 100 km².',
            title: 'Giandotti (1934)',
            definition: 'Wzór dla włoskich zlewni górskich; uwzględnia powierzchnię, długość cieku i deniwelację.',
            formula: f`T_c = 60 · \frac{4 \sqrt{A} + 1,5 L_g}{0,8 \sqrt{H_{śr} - H_{min}}}`,
            variables: [A, ['L_g', 'długość cieku głównego (gdy brak – długość zlewni)', 'km'], H_MEAN, H_MIN],
            unit: 'min',
            meaning: '$T_c$ rośnie z powierzchnią i długością cieku, maleje z deniwelacją $H_{śr} - H_{min}$.',
            range: 'Typowy zakres: $A$ 100–10 000 km², $L$ 1–300 km, $ΔH$ 20–3000 m (poza nim ostrzeżenie Hydrologu). Hydrograf liczy hydrogram do 250 km², więc większość zlewni leży poniżej zakresu metody.',
        },
        'hydro-tc-method:faa': {
            summary: 'Spływ powierzchniowy; L 0,015–3 km, spadek 0,5–10%, C 0,10–0,95.',
            title: 'FAA',
            definition: 'Metoda Federal Aviation Agency (odwodnienie lotnisk) dla spływu po względnie płaskich powierzchniach.',
            formula: f`T_c = 22,213 · (1,1 - C) \frac{L_{sp}^{0,5}}{I_{śr}^{1/3}}`,
            variables: [
                ['C', 'współczynnik spływu (pole „C (spływ)”; puste – z CN)', '–'],
                ['L_{sp}', 'długość spływu powierzchniowego (pole „L spływu”)', 'km'],
                ['I_{śr}', 'średni spadek terenu', 'm/m'],
            ],
            unit: 'min',
            meaning: 'Liczy tylko czas spływu po powierzchni na długości $L_{sp}$ – przepływ korytem nie jest uwzględniany. Większy $C$ skraca $T_c$.',
            range: 'Typowy zakres: $L$ 0,015–3 km, spadek 0,005–0,10 m/m, $C$ 0,10–0,95 (poza nim ostrzeżenie Hydrologu). Wymaga pola „L spływu”.',
        },
        'hydro-tc-method:kerby': {
            summary: 'Spływ warstwowy na płaskim terenie; L 0,01–0,366 km, spadek 0,1–1%, N 0,02–0,80.',
            title: 'Kerby (1959)',
            definition: 'Wzór dla płytkiego spływu warstwowego w małych, płaskich zlewniach.',
            formula: f`T_c = 36,37 · (L_{sp} N)^{0,467} I_{śr}^{-0,2335}`,
            variables: [
                ['L_{sp}', 'długość spływu powierzchniowego (pole „L spływu”)', 'km'],
                ['N', 'współczynnik oporu (pole „N (opór)”)', '–'],
                ['I_{śr}', 'średni spadek terenu; poniżej 0,002 zwiększany o 0,0005', 'm/m'],
            ],
            unit: 'min',
            meaning: 'Tylko spływ po powierzchni: $T_c$ rośnie z długością i szorstkością $N$, maleje ze spadkiem.',
            range: 'Typowy zakres: $L$ 0,01–0,366 km, spadek 0,001–0,01 m/m, $N$ 0,02–0,80 (poza nim ostrzeżenie Hydrologu). Wymaga pola „L spływu”.',
        },
        'hydro-tc-method:kerby_kirpich': {
            summary: 'Spływ po stoku (Kerby) + koryto (Kirpich); weryfikacja: 92 zlewnie w Teksasie, 0,65–388 km².',
            title: 'Kerby-Kirpich',
            definition: 'Metoda złożona: czas spływu po stoku (Kerby) plus czas przepływu korytem (Kirpich).',
            formula: [
                'T_c = t_{sp} + t_k',
                f`t_{sp} = 36,37 · (L_{sp} N)^{0,467} I_{śr}^{-0,2335}`,
                f`t_k = 3,981 · L_k^{0,77} I_g^{-0,385}`,
            ],
            variables: [
                ['L_{sp}', 'długość spływu po stoku: pole „L spływu” albo $L_{max} - L_k$, co najmniej 0,1 km', 'km'],
                ['N', 'współczynnik oporu', '–'],
                ['I_{śr}', 'średni spadek terenu', 'm/m'],
                ['L_k', 'długość koryta: $L_{BDOT}$, gdy większa od 0, inaczej $L_g$', 'km'],
                ['I_g', 'spadek cieku głównego', 'm/m'],
            ],
            unit: 'min',
            meaning: 'Obejmuje spływ po stoku i przepływ korytem. Podział drogi wody zależy od $L_{BDOT}$, a kilometr spływu po stoku trwa zwykle znacznie dłużej niż kilometr w korycie.',
            range: 'Zweryfikowana na 92 zlewniach w Teksasie (0,65–388 km²). Ostrzeżenia Hydrologu osobno dla części: stok – zakres Kerby’ego, koryto – $L$ 0,001–80 km, spadek 0,002–0,15 m/m. Spadki poniżej 0,002 są zwiększane o 0,0005 w obu częściach.',
        },
    };
})();
