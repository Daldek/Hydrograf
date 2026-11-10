/**
 * Hydrograf explanation texts for the (i) markers (js/info.js).
 *
 * Keys are API/morphometry field names (result rows), form control ids
 * (form fields), free keys used with data-info or Hydrograf.info.attach
 * (custom-rain, bdot_coverage and, for the network of „Sieć zlewni”
 * (js/network.js), network-headwater, network-tributary,
 * network-intermediate, reach_length_km, reach_slope_m_per_m and
 * reach_vector_length_km) and '<selectId>:<value>' for the options of the UH
 * model, Tc method and Nash estimation selects. Every entry is an object
 * with these optional fields:
 *
 *   title       name of the quantity (the label of the row when missing)
 *   symbol      its symbol, in the formula notation below
 *   definition  what the quantity is
 *   formula     a formula or an array of formulas
 *   variables   rows [symbol, meaning, unit] of the "gdzie:" list
 *   unit        unit of the value
 *   list        { title, items: [[term, text], ...] }, e.g. typical values
 *   meaning     "Znaczenie dla analizy": first the hydrological significance
 *               of the quantity (runoff timing, peak, hydrograph shape), then,
 *               after "\n", how Hydrograf uses it ("W Hydrografie …")
 *   range       applicability (option entries)
 *   note        limits and data caveats
 *   summary     option entries: the compact line under the select
 *   sources     literature the content rests on (author year), shown as
 *               "Źródła:" at the end of the entry
 *
 * Text may hold inline formulas between $...$. Formula notation, typeset
 * as MathML by info.js: x_i, x_{ab} subscript; x^2, x^{0,77} superscript;
 * \frac{a}{b}; \sqrt{a}; \text{...} upright text; { } groups; ( ) and [ ]
 * are fences that take scripts as a whole; a run of Latin letters is one
 * identifier (one letter italic, more letters upright: max, CN); a Greek
 * letter is one identifier; numbers use a decimal comma; '-' is a minus.
 *
 * Every formula, unit and statement about what Hydrograf computes follows
 * the code: Hydrograf backend (core/catchment_graph.py,
 * core/watershed_service.py, core/morphometry.py, core/land_cover.py,
 * core/precipitation.py, api/endpoints/hydrograph.py; the network:
 * core/network_tree.py, core/network_delineation.py, core/handoff.py) and
 * Hydrolog, the version the backend pins (docs/INFO_TEXTS_SOURCES.md,
 * "Wersja Hydrologu"; time/concentration.py, morphometry/watershed_params.py,
 * runoff/*.py, precipitation/hietogram.py, routing/cunge.py). Hydrological
 * statements rest on the literature in `sources`; every claim, its verdict
 * and the place where the source was checked are listed in
 * docs/INFO_TEXTS_SOURCES.md.
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
    var L_MAX = ['L_{max}', 'najdłuższa droga spływu od punktu zlewni najdalszego hydraulicznie do ujścia', 'km'];
    var H_POCZ = ['H_{pocz}', 'wysokość początku najdłuższej drogi spływu (najdalszej hydraulicznie komórki NMT zlewni, zwykle na dziale wodnym)', 'm n.p.m.'];
    var L_SP = ['L_{sp}', 'długość spływu powierzchniowego: od początku najdłuższej drogi spływu do sieci cieków z NMT', 'km'];

    var BETA_PEAK = {
        formula: f`t_s = \frac{α - 1}{α + β - 2}`,
        variables: [
            ['t_s', 'położenie szczytu opadu jako ułamek czasu trwania (dla $α, β > 1$)', '–'],
            ['α, β', 'parametry rozkładu Beta', '–'],
        ],
    };

    /**
     * Second part of "Znaczenie dla analizy" for a shape index: Hydrograf
     * computes it only for the record; the watershed shape reaches the
     * hydrograph through the flow lengths (backend api/endpoints/hydrograph.py).
     */
    function shapeUse(symbol) {
        return 'W Hydrografie ' + symbol + ' nie wchodzi bezpośrednio do obliczeń hydrogramu; kształt zlewni działa pośrednio – przez długości $L$, $L_g$ i $L_c$, od których zależą czas koncentracji oraz parametry modeli Snydera i Nasha (Lutz).';
    }

    window.Hydrograf.infoTexts = {
        // ── Parametry podstawowe ───────────────────────────────────────
        area_km2: {
            title: 'Powierzchnia zlewni',
            symbol: 'A',
            definition: 'Powierzchnia obszaru, z którego woda spływa do ujścia: suma powierzchni zlewni cząstkowych wyznaczonych z NMT – klikniętej i wszystkich położonych powyżej niej.',
            formula: 'A = ∑ A_i',
            variables: [['A_i', 'powierzchnia i-tej zlewni cząstkowej: liczba komórek NMT razy powierzchnia komórki', 'km²']],
            unit: 'km²',
            meaning: 'Od powierzchni zależy objętość odpływu ($V = P_e·A$) i skala szczytu; większa zlewnia reaguje jednak wolniej – drogi spływu są dłuższe – więc szczyt rośnie wolniej niż proporcjonalnie do $A$.\nW Hydrografie $A$ skaluje hydrogram jednostkowy każdego modelu (przy tych samych parametrach czasowych szczyt jest proporcjonalny do $A$) i wchodzi do wzoru Giandottiego oraz regresji urbanizacyjnej. Hietogram i hydrogram są liczone dla zlewni do 250 km².',
            sources: 'Chow i in. 1988; USDA-NRCS 2007 (NEH 630-16); USDA-NRCS 2010 (NEH 630-15)',
        },
        perimeter_km: {
            title: 'Obwód zlewni',
            symbol: 'P',
            definition: 'Długość granicy zlewni (działu wodnego). Granica powstaje z połączenia zlewni cząstkowych, uproszczonego z tolerancją 5 m i wygładzonego.',
            unit: 'km',
            meaning: 'Sam obwód nie jest parametrem odpływu – jego znaczenie hydrologiczne ujawnia się we wskaźnikach kształtu. Zmierzona długość granicy zależy od skali mapy lub rozdzielczości NMT i od uogólnienia granicy.\nW Hydrografie wchodzi tylko do wskaźników $C_z$, $C_k$ i $R_p$; nie jest daną wejściową metod $T_c$ ani modeli hydrogramu.',
            note: 'Uproszczenie i wygładzenie usuwają schodki rastra, więc obwód jest krótszy niż obrys komórek NMT. Wskaźniki zależne od obwodu porównuj tylko między zlewniami wyznaczonymi tą samą metodą.',
            sources: 'Bendjoudi i Hubert 2002; Baścik 2006',
        },
        length_km: {
            title: 'Długość zlewni',
            symbol: 'L',
            definition: 'Długość zlewni mierzona wzdłuż najdłuższej drogi spływu od punktu najdalszego hydraulicznie do ujścia, po kierunkach spływu z NMT. Gdy jej brak – największa odległość w linii prostej od ujścia do granicy zlewni.',
            unit: 'km',
            meaning: 'Dłuższa droga spływu wydłuża czas koncentracji i opóźnienie odpływu, co daje późniejszy i niższy szczyt.\nW Hydrografie wchodzi do wskaźników kształtu $C_w$, $C_f$, $C_l$ i do średniej szerokości $B$. Metody Tc nie biorą $L$: NRCS, Kirpich i Kerby-Kirpich używają najdłuższej drogi spływu $L_{max}$ (gdy jest zmierzona – ta sama wartość), a Giandotti – tylko długości cieku głównego $L_g$.',
            note: 'W klasycznych wskaźnikach kształtu (Schumm, Chorley) długość zlewni to odcinek prosty; droga spływu jest dłuższa, więc wartości wskaźników nie są wprost porównywalne z literaturą.',
            sources: 'USDA-NRCS 2010 (NEH 630-15); Baścik 2006; Schumm 1956',
        },
        mean_width_km: {
            title: 'Średnia szerokość zlewni',
            symbol: 'B',
            definition: 'Szerokość prostokąta o powierzchni i długości zlewni.',
            formula: f`B = \frac{A}{L}`,
            variables: [A, L],
            unit: 'km',
            meaning: 'Przy tej samej powierzchni mniejsza szerokość oznacza zlewnię bardziej wydłużoną: czasy dopływu wody z różnych części zlewni do ujścia rozkładają się na dłuższy okres, więc fala jest zwykle niższa, późniejsza i dłuższa niż w zlewni zwartej. Efekt zależy też od układu sieci rzecznej, położenia ujścia i kierunku przemieszczania się opadu.\n' + shapeUse('$B$'),
            sources: 'Horton 1932; Baścik 2006; USDA-NRCS 2007 (NEH 630-16); Wisler i Brater 1959; Linsley i in. 1949',
        },
        elevation_min_m: {
            title: 'Wysokość minimalna',
            symbol: 'H_{min}',
            definition: 'Najniższa wysokość terenu w zlewni według NMT. Hydrograf przyjmuje ją także jako wysokość ujścia.',
            unit: 'm n.p.m.',
            meaning: 'Wysokość ujścia jest poziomem odniesienia deniwelacji: im wyżej zlewnia wznosi się nad ujście, tym krótszy czas koncentracji (Giandotti) i wyższy przepływ maksymalny w polskim równaniu regionalnym.\nW Hydrografie to punkt odniesienia deniwelacji $ΔH = H_{max} - H_{min}$ we wskaźnikach rzeźby ($R$, $R_p$, $R_n$, $HI$), deniwelacji $H_{śr} - H_{min}$ w metodzie Giandottiego i spadku najdłuższej drogi spływu $I_{dr}$ (Kirpich, Kerby-Kirpich).',
            note: 'W analizach hydrologicznych za wysokość minimalną przyjmuje się często rzędną zwierciadła wody w przekroju zamykającym przy najniższym stanie; Hydrograf bierze najniższą komórkę NMT.',
            sources: 'Baścik 2006; Giandotti 1934 (za Grimaldi i in. 2012); KZGW 2017',
        },
        elevation_max_m: {
            title: 'Wysokość maksymalna',
            symbol: 'H_{max}',
            definition: 'Najwyższa wysokość terenu w zlewni według NMT.',
            unit: 'm n.p.m.',
            meaning: 'Wyznacza deniwelację zlewni; duża deniwelacja sprzyja szybkiemu spływowi i gwałtownym wezbraniom, choć w danych z różnych zlewni nie zawsze to widać.\nW Hydrografie $ΔH = H_{max} - H_{min}$ wchodzi do wskaźników rzeźby i liczby chropowatości; nie wchodzi do obliczeń $T_c$ ani hydrogramu.',
            sources: 'Baścik 2006; Patton i Baker 1976; Carlston 1963',
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
            meaning: 'Średnia wysokość nad ujściem wyznacza deniwelację w metodzie Giandottiego: im mniejsza, tym dłuższy czas koncentracji. Od $H_{śr}$ zależy też całka hipsometryczna $HI$.\nW Hydrografie wchodzi do $T_c$ tylko w metodzie Giandottiego ($H_{śr} - H_{min}$) i do $HI$.',
            sources: 'Baścik 2006; Giandotti 1934 (za Grimaldi i in. 2012); Pike i Wilson 1971',
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
            meaning: 'Im większe nachylenie stoków, tym szybszy spływ powierzchniowy, mniej wody wsiąka i paruje, a czas koncentracji jest krótszy – szczyt wcześniejszy i wyższy. To spadek stoków, nie cieku.\nW Hydrografie używa go tylko metoda Tc NRCS (spadek terenu $Y$ równania opóźnienia). FAA, Kerby i Kerby-Kirpich biorą spadek odcinka spływu powierzchniowego, a Kirpich – spadek najdłuższej drogi spływu; średni spadek terenu żadnego z nich nie zastępuje.',
            sources: 'Baścik 2006; USDA-NRCS 2010 (NEH 630-15); USDA-NRCS 2007 (NEH 630-16)',
        },
        channel_length_km: {
            title: 'Długość cieku głównego',
            symbol: 'L_g',
            definition: 'Ciek główny biegnie od ujścia w górę sieci cieków wyznaczonej z NMT, na każdym rozwidleniu w stronę dopływu o największej powierzchni zlewni. Jego długość to suma długości odcinków.',
            formula: 'L_g = ∑ l_j',
            variables: [['l_j', 'długość j-tego odcinka sieci na drodze cieku głównego', 'km']],
            unit: 'km',
            meaning: 'Dłuższy ciek główny wydłuża czas opóźnienia, więc szczyt hydrogramu jest późniejszy i niższy (Snyder, Lutz, Giandotti).\nW Hydrografie używają jej metoda Tc Giandottiego oraz modele Snydera i Nasha (Lutz). Bez niej metoda Giandottiego zgłasza brak danych – długość zlewni jej nie zastępuje.',
            note: 'Sieć cieków z NMT zaczyna się tam, gdzie powierzchnia spływająca do danego miejsca przekracza próg akumulacji, więc ciek nie sięga działu wodnego, a jego długość zależy od progu sieci. Snyder i Lutz mierzą ciek główny aż do działu wodnego, więc $L_g$ jest od tej długości krótsza. Ciek główny nie musi biec najdłuższą drogą spływu: na rozwidleniu idzie w stronę dopływu o większej powierzchni zlewni, a najdłuższa droga spływu może iść dłuższym dopływem o mniejszej powierzchni. Dlatego $L_g$ i „Spływ powierzchniowy – długość” nie muszą dawać razem „Najdłuższej drogi spływu”; metoda Kerby-Kirpich bierze jako koryto $L_{max} - L_{sp}$ wzdłuż najdłuższej drogi spływu, nie $L_g$.',
            sources: 'KZGW 2017; Tarboton i in. 1991; Giandotti 1934 (za Grimaldi i in. 2012)',
        },
        real_channel_length_km: {
            title: 'Długość cieku wg BDOT10k',
            symbol: 'L_{BDOT}',
            definition: 'Długość części cieku głównego od ujścia w górę, która pokrywa się z ciekami BDOT10k. Przerwy do dwóch odcinków są wliczane; liczenie kończy się na dłuższej przerwie.',
            unit: 'km',
            meaning: 'Odcinek z korytem, w którym woda płynie znacznie szybciej niż po stoku: dłuższy odcinek korytowy przy tej samej drodze spływu daje krótszy czas koncentracji.\nW Hydrografie to wartość informacyjna – nie wchodzi do obliczeń $T_c$ ani hydrogramu; w metodzie Kerby-Kirpich koryto zaczyna się tam, gdzie najdłuższa droga spływu dochodzi do sieci cieków z NMT („Spływ powierzchniowy – długość”). Jej udział w $L_g$ to „Pokrycie BDOT” w sekcji Sieć rzeczna.',
            note: 'Odcinek sieci z NMT uznaje się za ciek BDOT10k, gdy co najmniej 50% jego długości leży nie dalej niż 25 m od cieku BDOT10k. Wartość 0 – odcinek przy ujściu nie jest takim ciekiem.',
            sources: 'USDA-SCS 1986 (TR-55); Roussel i in. 2005',
        },
        channel_slope_m_per_m: {
            title: 'Spadek cieku głównego',
            symbol: 'I_g',
            definition: 'Różnica wysokości wzdłuż cieku głównego podzielona przez jego długość.',
            formula: f`I_g = \frac{H_{źr} - H_{min,u}}{1000 · L_g}`,
            variables: [
                ['H_{źr}', 'wysokość źródła cieku głównego: górnego końca cieku w sieci z NMT', 'm n.p.m.'],
                ['H_{min,u}', 'najniższa wysokość zlewni cząstkowej przy ujściu', 'm n.p.m.'],
                L_G,
            ],
            unit: 'm/m (w tabeli w %)',
            meaning: 'Większy spadek cieku przyspiesza przepływ korytem: skraca czas koncentracji i czas do szczytu, więc szczyt jest wcześniejszy i wyższy.\nW Hydrografie używa go tylko estymacja Nasha metodą Lutza ($t_p ∝ I_g^{-0,39}$). Metody Tc Kirpich i Kerby-Kirpich biorą spadek najdłuższej drogi spływu $I_{dr}$, liczony od działu wodnego, a nie od źródła cieku.',
            note: 'Źródło to początek cieku w sieci z NMT, tam gdzie powierzchnia spływająca przekracza próg akumulacji, więc spadek zależy od progu sieci. Metoda Lutza zakłada spadek wyrównany (z równych pól pod i nad linią spadku), a nie spadek między końcami cieku.',
            sources: 'Kirpich 1940 (za Roussel i in. 2005); KZGW 2017; Baścik 2006',
        },
        flow_path_length_km: {
            title: 'Najdłuższa droga spływu',
            symbol: 'L_{max}',
            definition: 'Długość drogi spływu od najdalszej hydraulicznie komórki NMT zlewni (o największej odległości spływu do ujścia) do ujścia, po kierunkach spływu z NMT. Ta komórka leży na grzbiecie – zwykle na dziale wodnym, ale może leżeć na grzbiecie wewnątrz zlewni, między dwiema dolinami.',
            formula: 'L_{max} = max_i d_i - d_u',
            variables: [
                ['d_i', 'najdłuższa droga spływu z i-tej zlewni cząstkowej do ujścia całego obszaru danych', 'km'],
                ['d_u', 'droga spływu z ujścia zlewni do ujścia obszaru danych', 'km'],
            ],
            unit: 'km',
            meaning: 'Czas koncentracji liczy się od hydraulicznie najdalszego punktu zlewni; w metodach Tc reprezentuje go najdłuższa droga spływu – dłuższa droga wydłuża $T_c$, opóźnia i obniża szczyt.\nW Hydrografie to długość metod NRCS i Kirpicha; w Kerby-Kirpich koryto ma długość $L_{max} - L_{sp}$, więc $L_{max}$ musi być większa od długości spływu powierzchniowego. Można ją zmienić w trybie zaawansowanym.',
            sources: 'USDA-NRCS 2010 (NEH 630-15); Roussel i in. 2005; USDA-SCS 1986 (TR-55)',
        },
        flow_path_slope_m_per_m: {
            title: 'Spadek najdłuższej drogi spływu',
            symbol: 'I_{dr}',
            definition: 'Różnica wysokości między początkiem najdłuższej drogi spływu (punktem zlewni najdalszym hydraulicznie) a ujściem, podzielona przez długość tej drogi.',
            formula: f`I_{dr} = \frac{H_{pocz} - H_{min}}{1000 · L_{max}}`,
            variables: [H_POCZ, ['H_{min}', 'najniższa wysokość terenu w zlewni, przyjmowana jako wysokość ujścia', 'm n.p.m.'], L_MAX],
            unit: 'm/m (w tabeli w %)',
            meaning: 'U Kirpicha spadek to różnica wysokości najdalszego punktu zlewni i ujścia podzielona przez długość drogi wody między nimi; w Kerby-Kirpich to spadek cieku głównego od działu wodnego do ujścia, liczony na całej tej drodze. Większy spadek skraca czas koncentracji ($T_c ∝ I_{dr}^{-0,385}$), więc szczyt jest wcześniejszy i wyższy.\nW Hydrografie to spadek metody Kirpicha i części korytowej Kerby-Kirpich (w Kerby-Kirpich poniżej 0,002 Hydrolog zwiększa go o 0,0005). Można go zmienić w trybie zaawansowanym.',
            note: 'Najdalszy punkt nie musi być najwyższym, więc $I_{dr}$ nie jest deniwelacją zlewni podzieloną przez $L_{max}$; nie jest też spadkiem cieku głównego $I_g$, który liczy się od źródła cieku w sieci z NMT. Wysokości pochodzą z NMT z wypełnionymi zagłębieniami. Pusta wartość – brak wysokości początku drogi albo spadek nie jest dodatni; Hydrograf nie podstawia wtedy innego spadku.',
            sources: 'Kirpich 1940 (za Fang i in. 2005 i Mota i Kobiyama 2015); Roussel i in. 2005; TxDOT 2019',
        },
        overland_length_km: {
            title: 'Spływ powierzchniowy – długość',
            symbol: 'L_{sp}',
            definition: 'Długość początkowego odcinka najdłuższej drogi spływu, na którym woda spływa po stoku: od jej początku (punktu zlewni najdalszego hydraulicznie), po kierunkach spływu z NMT, do pierwszej komórki sieci cieków z NMT wyznaczonej przy progu akumulacji, przy którym wyznaczono zlewnię.',
            unit: 'km',
            meaning: 'Spływ po stoku jest wolny, więc nawet krótki jego odcinek może stanowić dużą część czasu dopływu w małej zlewni. W metodzie Kerby’ego to droga od najdalszego punktu do wyraźnego koryta, w metodzie FAA – do wpustu.\nW Hydrografie to długość metod FAA i Kerby oraz części spływu po stoku w Kerby-Kirpich (część korytowa ma długość $L_{max} - L_{sp}$). Można ją zmienić w trybie zaawansowanym – wtedy sprawdź też spadek.',
            note: 'Koniec odcinka zależy od progu sieci cieków: im większy próg, tym dalej od działu wodnego zaczyna się sieć i tym dłuższy odcinek. Przy progach 1 i 10 km² obejmuje on też fragmenty, w których płynie już ciek, i może przekraczać 0,366 km (1200 ft) – górną granicę danych Kerby’ego; nomogram FAA sięga 0,24 km, dłuższe odcinki liczy się wzorem. Hydrograf mierzy odcinek wzdłuż drogi spływu, Kerby – w linii prostej, równolegle do spadku. Pusta wartość – odcinka nie zmierzono (np. początek drogi leży już w sieci cieków); FAA, Kerby i Kerby-Kirpich zgłaszają wtedy brak danych. Odcinek leży na początku najdłuższej drogi spływu, która może biec dłuższym dopływem o mniejszej powierzchni zlewni niż ciek główny (ten na każdym rozwidleniu idzie w stronę większej powierzchni), więc $L_{sp}$ i „Długość cieku głównego” nie muszą dawać razem $L_{max}$. Droga spływu może też dochodzić do cieku z boku, poniżej jego źródła – cieku nad tym miejscem nie ma w $L_{max}$. Część korytową Kerby-Kirpich liczy więc jako $L_{max} - L_{sp}$ wzdłuż najdłuższej drogi spływu.',
            sources: 'Kerby 1959 (za Fang i in. 2005); FAA 1970; Roussel i in. 2005; Tarboton i in. 1991; USDA-SCS 1986 (TR-55)',
        },
        overland_slope_m_per_m: {
            title: 'Spływ powierzchniowy – spadek',
            symbol: 'I_{sp}',
            definition: 'Spadek odcinka spływu powierzchniowego: różnica wysokości jego początku (punktu zlewni najdalszego hydraulicznie) i końca (pierwszej komórki sieci cieków z NMT) podzielona przez jego długość.',
            formula: f`I_{sp} = \frac{H_{pocz} - H_k}{1000 · L_{sp}}`,
            variables: [H_POCZ, ['H_k', 'wysokość pierwszej komórki sieci cieków na najdłuższej drodze spływu', 'm n.p.m.'], L_SP],
            unit: 'm/m (w tabeli w %)',
            meaning: 'Większy spadek przyspiesza spływ po stoku i skraca czas koncentracji. FAA i Kerby biorą spadek powierzchni, po której spływa woda – nie średni spadek zlewni ani spadek cieku.\nW Hydrografie to spadek metod FAA i Kerby oraz części spływu po stoku w Kerby-Kirpich (w Kerby i Kerby-Kirpich poniżej 0,002 Hydrolog zwiększa go o 0,0005). Można go zmienić w trybie zaawansowanym.',
            note: 'Wysokości pochodzą z NMT z wypełnionymi zagłębieniami, tego samego co statystyki wysokości zlewni. Pusta wartość – odcinka nie zmierzono albo spadek nie jest dodatni; Hydrograf nie podstawia wtedy innego spadku.',
            sources: 'FAA 1970; Kerby 1959 (za Roussel i in. 2005); TxDOT 2019; Cleveland i in. 2012 (TxDOT 0-6382-P1)',
        },
        divide_flow_path_km: {
            title: 'Najdłuższa droga spływu od granicy zlewni',
            symbol: 'L_{dz}',
            definition: 'Długość drogi spływu od najdalszej hydraulicznie komórki NMT na granicy zlewni (komórki zlewni z sąsiadem poza zlewnią) do ujścia, po kierunkach spływu z NMT. Nigdy nie jest dłuższa od najdłuższej drogi spływu $L_{max}$; jest jej równa, gdy najdalszy hydraulicznie punkt zlewni leży na jej granicy.',
            formula: 'L_{dz} = max_k d_k - d_u',
            variables: [
                ['d_k', 'droga spływu z k-tej komórki na granicy zlewni do ujścia obszaru danych', 'km'],
                ['d_u', 'droga spływu z ujścia zlewni do ujścia obszaru danych', 'km'],
            ],
            unit: 'km',
            meaning: 'W metodach Tc długość spływu mierzy się od działu wodnego do ujścia; gdy najdalszy hydraulicznie punkt leży na grzbiecie wewnątrz zlewni, $L_{dz}$ pokazuje, o ile krótsza jest droga od granicy.\nW Hydrografie nie wchodzi do obliczeń $T_c$ ani hydrogramu, które używają $L_{max}$.',
            note: 'Granicę tworzą komórki zlewni cząstkowych, z których złożono zlewnię, a nie wygładzona linia granicy na mapie. Mapa pokazuje tylko część tej drogi niewspólną z najdłuższą drogą spływu – od granicy do miejsca, gdzie się z nią łączy; dalej obie biegną tą samą drogą. Wiersza nie ma, gdy najdalszy hydraulicznie punkt zlewni leży na jej granicy (obie drogi są wtedy jedną) albo brak rastra zlewni cząstkowych progu, przy którym wyznaczono zlewnię.',
            sources: 'USDA-NRCS 2010 (NEH 630-15)',
        },
        cn: {
            title: 'Parametr CN (krzywa odpływu)',
            symbol: 'CN',
            definition: 'Bezwymiarowy parametr metody SCS-CN (0–100) opisujący zdolność zlewni do zatrzymania opadu; w literaturze zależy od pokrycia terenu, grupy hydrologicznej gleby (HSG) i uwilgotnienia. Hydrograf liczy go dla przeciętnego uwilgotnienia (AMC II) jako średnią ważoną powierzchnią z CN kompleksów glebowo-roślinnych: części zlewni, w których klasa pokrycia terenu BDOT10k leży na jednej grupie HSG.',
            formula: f`CN = \frac{∑ A_i CN_i}{∑ A_i}`,
            variables: [
                ['A_i', 'powierzchnia i-tego kompleksu (klasa pokrycia terenu na grupie HSG) w zlewni', 'm²'],
                ['CN_i', 'CN kompleksu: wartość tablic TR-55 dla typu pokrycia przypisanego klasie i dla grupy HSG', '–'],
            ],
            unit: '–',
            meaning: 'Wyższy CN – mniejsze straty i większy odpływ: CN wyznacza retencję $S$ i straty początkowe $I_a$, a przez nie objętość i kulminację fali; wynik metody SCS-CN jest bardzo wrażliwy na CN.\nW Hydrografie CN wchodzi do strat SCS-CN (po przeliczeniu według wybranego AMC) i do metody Tc NRCS (CN dla AMC II). Współczynnika spływu $C$ metody FAA Hydrograf z CN nie wylicza.',
            note: 'Typy pokrycia TR-55: las – las w dobrym stanie; grunty orne – zboża w rzędach, stan dobry; łąki – łąka koszona; zabudowa mieszkaniowa – działki 1/3 akra (30% powierzchni nieprzepuszczalnych), wielorodzinna – 1/8 akra (65%); zabudowa przemysłowa – tereny przemysłowe (72%), handlowo-usługowa – handlowe (85%); tereny komunikacyjne – drogi utwardzone z rowami otwartymi, wraz z pasem drogowym; place utwardzone i wody – CN 98; inne – tereny otwarte w średnim stanie, trawniki parków, terenów sportowo-rekreacyjnych i lotnisk – tereny otwarte w dobrym stanie, place nieutwardzone – drogi gruntowe, wyrobiska i zwałowiska – grunt odsłonięty. Część pokrycia poza mapą HSG dostaje grupy reszty zlewni w ich udziałach, a gdy w zlewni nie ma żadnej – grupę B. Mapa HSG (SoilGrids 250 m, grupa najmniej przepuszczalnej warstwy do głębokości 100 cm) jest zgrubna; pod mokradłami z BDOT10k gleba ma grupę D (podmokła, nieodwodniona). Przy dużym zróżnicowaniu CN w zlewni średnia ważona może zaniżać lub zawyżać odpływ. Bez danych o pokryciu terenu hydrogram jest liczony z CN = 75.',
            sources: 'USDA-SCS 1986 (TR-55); USDA-NRCS 2004 (NEH 630-9, NEH 630-10); USDA-NRCS 2009 (NEH 630-7); Ponce i Hawkins 1996',
        },
        latitude: {
            title: 'Szerokość geograficzna ujścia',
            symbol: 'φ',
            definition: 'Położenie ujścia zlewni w układzie WGS84, przeliczone z układu PL-1992. Ujście to dolny koniec klikniętego odcinka cieku, dosunięty do granicy zlewni, gdy leży poza nią.',
            unit: '°N',
            meaning: 'W Hydrografie lokalizuje ujście – nie wchodzi do obliczeń. Opad PMAXTP to średnia w zlewni (wieloboki Thiessena), a nie wartość w ujściu.',
        },
        longitude: {
            title: 'Długość geograficzna ujścia',
            symbol: 'λ',
            definition: 'Położenie ujścia zlewni w układzie WGS84, przeliczone z układu PL-1992. Ujście to dolny koniec klikniętego odcinka cieku, dosunięty do granicy zlewni, gdy leży poza nią.',
            unit: '°E',
            meaning: 'W Hydrografie lokalizuje ujście – nie wchodzi do obliczeń. Opad PMAXTP to średnia w zlewni (wieloboki Thiessena), a nie wartość w ujściu.',
        },
        elevation_m: {
            title: 'Wysokość ujścia',
            symbol: 'H_u',
            definition: 'Wysokość przyjęta dla ujścia: najniższa wysokość terenu w zlewni według NMT ($H_{min}$), a nie odczyt w punkcie ujścia.',
            unit: 'm n.p.m.',
            meaning: 'W Hydrografie to ta sama wartość co „Wysokość min.” – punkt odniesienia deniwelacji zlewni i, w metodzie Giandottiego, wyniesienia średniej wysokości nad ujście.',
        },

        // ── Wskaźniki kształtu ─────────────────────────────────────────
        compactness_coefficient: {
            title: 'Wskaźnik zwartości Graveliusa',
            symbol: 'C_z',
            definition: 'Stosunek obwodu zlewni do obwodu koła o tej samej powierzchni (Gravelius 1914).',
            formula: f`C_z = \frac{P}{2 \sqrt{π A}}`,
            variables: [P, A],
            unit: '–',
            meaning: 'Dla koła $C_z = 1$, dla kwadratu ≈ 1,13; im większy, tym zlewnia mniej zwarta – wydłużona lub o poszarpanej granicy. Duże $C_z$ wynikające z wydłużenia sprzyja niższym, późniejszym i dłuższym falom wezbraniowym; wskaźnik rośnie jednak także od drobnych nieregularności granicy, które nie zmieniają odpływu, i nie odróżnia ujścia bocznego od czołowego.\n' + shapeUse('$C_z$'),
            note: 'Z nierówności izoperymetrycznej $C_z ≥ 1$. Wartość poniżej 1 oznacza niespójność danych: $A$ to suma komórek NMT, a $P$ – długość wygładzonej granicy. Wartość zależy od rozdzielczości, z jaką wyznaczono obwód.',
            sources: 'Gravelius 1914 (za Horton 1932 oraz Bendjoudi i Hubert 2002); USDA-NRCS 2007 (NEH 630-16); Baścik 2006',
        },
        circularity_ratio: {
            title: 'Wskaźnik kolistości Millera',
            symbol: 'C_k',
            definition: 'Stosunek powierzchni zlewni do powierzchni koła o tym samym obwodzie (Miller 1953).',
            formula: f`C_k = \frac{4 π A}{P^2}`,
            variables: [A, P],
            unit: '–',
            meaning: 'Dla koła $C_k = 1$, dla kwadratu ≈ 0,785; mniejsze wartości – zlewnia mniej zwarta. Jest odwrotnością kwadratu $C_z$ i niesie tę samą informację: niskie $C_k$ wynikające z wydłużenia sprzyja niższym i dłuższym falom, ale wskaźnik reaguje też na drobne nieregularności granicy, które nie zmieniają odpływu.\n' + shapeUse('$C_k$'),
            note: 'Z nierówności izoperymetrycznej $C_k ≤ 1$. Wartość powyżej 1 nie opisuje kształtu, tylko niespójność $A$ (suma komórek NMT) i $P$ (wygładzona granica).',
            sources: 'Miller 1953 (za Chorley i in. 1957 i Różycka 2015); Bendjoudi i Hubert 2002; USDA-NRCS 2007 (NEH 630-16)',
        },
        elongation_ratio: {
            title: 'Wskaźnik wydłużenia Schumma',
            symbol: 'C_w',
            definition: 'Stosunek średnicy koła o powierzchni zlewni do długości zlewni (Schumm 1956).',
            formula: f`C_w = \frac{2}{L} \sqrt{\frac{A}{π}}`,
            variables: [A, L],
            unit: '–',
            meaning: 'Dla koła ($L$ równe średnicy) $C_w = 1$; im mniejszy, tym zlewnia bardziej wydłużona – dłuższe drogi spływu i zwykle niższy, późniejszy i dłuższy hydrogram niż w zlewni zwartej o tej samej powierzchni. Przy prostoliniowej długości zlewni $C_w$ wynosi zwykle 0,6–1,0, bliżej 1 przy słabej rzeźbie.\n' + shapeUse('$C_w$'),
            note: 'U Schumma $L$ to maksymalna długość zlewni w linii prostej; tu jest to najdłuższa droga spływu, więc $C_w$ wychodzi niższy niż w klasycznej definicji i nie należy go wprost porównywać z wartościami z literatury.',
            sources: 'Schumm 1956; Kumar 2011; USDA-NRCS 2007 (NEH 630-16); Baścik 2006',
        },
        form_factor: {
            title: 'Wskaźnik formy Hortona',
            symbol: 'C_f',
            definition: 'Stosunek powierzchni zlewni do kwadratu jej długości (Horton 1932).',
            formula: f`C_f = \frac{A}{L^2}`,
            variables: [A, L],
            unit: '–',
            meaning: 'Dla koła ($L$ równe średnicy) $C_f = π/4 ≈ 0,785$; mniejsze wartości – zlewnia wydłużona: dłuższe drogi spływu i zwykle niższa, dłuższa fala, a zlewnia rzadziej jest w całości objęta intensywnym opadem. Horton uznał wskaźnik za miarodajny dla wezbrań zlewni długich i wąskich, ale mało czuły w zlewniach o nieregularnym kształcie, zwłaszcza na glebach przepuszczalnych.\n' + shapeUse('$C_f$'),
            note: '$L$ to najdłuższa droga spływu – kręta droga spływu obniża $C_f$. Przy ujściu z boku zlewni $C_f$ może przekraczać $π/4$.',
            sources: 'Horton 1932; Wisler i Brater 1959; USDA-NRCS 2007 (NEH 630-16); USDA-NRCS 2021 (NEH 650-2)',
        },
        lemniscate_ratio: {
            title: 'Wskaźnik lemniskaty Chorleya',
            symbol: 'C_l',
            definition: 'Stosunek powierzchni koła o średnicy równej długości zlewni do powierzchni zlewni – parametr $k$ pętli lemniskaty, z którą Chorley i in. (1957) porównali kształt zlewni.',
            formula: f`C_l = \frac{π L^2}{4 A}`,
            variables: [L, A],
            unit: '–',
            meaning: 'Dla koła $C_l = 1$; im większy, tym zlewnia bardziej wydłużona, z dłuższymi drogami spływu i zwykle bardziej spłaszczonym, późniejszym hydrogramem. Niesie tę samą informację co $C_f$ i $C_w$: $C_l = π/(4 C_f) = 1/C_w^2$.\n' + shapeUse('$C_l$'),
            note: '$L$ to najdłuższa droga spływu – kręta droga spływu podwyższa $C_l$. To parametr $k$ Chorleya, a nie jego „Lemniscate Ratio” (stosunek obwodów).',
            sources: 'Chorley i in. 1957; USDA-NRCS 2007 (NEH 630-16)',
        },

        // ── Rzeźba terenu ──────────────────────────────────────────────
        relief_ratio: {
            title: 'Wskaźnik rzeźby – spadek zlewni ψ (Meltona)',
            symbol: 'R',
            definition: 'Deniwelacja zlewni odniesiona do pierwiastka z jej powierzchni, czyli do boku kwadratu o tej samej powierzchni. W metodyce KZGW (2017) to średni spadek zlewni ψ, w literaturze anglojęzycznej – wskaźnik Meltona ($R/1000$).',
            formula: f`R = \frac{H_{max} - H_{min}}{\sqrt{A}}`,
            variables: [H_MAX, H_MIN, A],
            unit: '‰ (m/km)',
            meaning: 'Pozwala porównywać rzeźbę zlewni różnej wielkości: większy $R$ – teren bardziej stromy i urozmaicony. W polskim równaniu regionalnym (KZGW 2017) przepływ maksymalny $Q_{1%}$ rośnie jak $ψ^{0,35}$. Wskaźnik Meltona służy też do odróżniania zlewni, w których występują powodzie, od zlewni ze spływami gruzowymi – progi wyznaczono jednak dla górskich zlewni Kolumbii Brytyjskiej, więc dla większości obszarów Hydrografu mają ograniczone zastosowanie.\nW Hydrografie $R$ nie wchodzi do obliczeń $T_c$ ani hydrogramu; rzeźba działa w nich przez spadki $I_{śr}$ i $I_g$ oraz, w metodzie Giandottiego, przez $H_{śr} - H_{min}$.',
            note: 'W podręcznikach (np. Baścik 2006) „wskaźnik rzeźby” Strahlera to deniwelacja odniesiona do długości zlewni, a nie do $\\sqrt{A}$.',
            sources: 'KZGW 2017; Melton 1965 (za Chen i in. 2022); Wilford i in. 2004; Millard i in. 2006; Baścik 2006',
        },
        divide_slope: {
            title: 'Spadek działu wodnego',
            symbol: 'R_p',
            definition: 'Deniwelacja zlewni odniesiona do długości jej granicy (obwodu) – średni spadek działu wodnego, zwany też wskaźnikiem urzeźbienia działu wodnego.',
            formula: f`R_p = \frac{H_{max} - H_{min}}{P}`,
            variables: [H_MAX, H_MIN, P],
            unit: '‰ (m/km)',
            meaning: 'Deniwelacja przypadająca na kilometr działu wodnego – miara urzeźbienia granicy zlewni.\nW Hydrografie $R_p$ nie wchodzi do obliczeń $T_c$ ani hydrogramu.',
            note: 'W definicji podręcznikowej licznikiem jest deniwelacja wzdłuż działu wodnego; Hydrograf bierze deniwelację całej zlewni. Wartość zależy od obwodu, który skraca wygładzenie granicy.',
            sources: 'Baścik 2006',
        },
        asymmetry_coefficient: {
            title: 'Współczynnik asymetrii',
            symbol: 'α',
            definition: 'Różnica powierzchni lewo- i prawobrzeżnej części zlewni (podział wzdłuż cieku głównego) odniesiona do połowy powierzchni zlewni; przyjmuje wartości od −2 do 2.',
            formula: f`α = \frac{2 (A_L - A_P)}{A}`,
            variables: [
                ['A_L', 'powierzchnia części lewobrzeżnej', 'km²'],
                ['A_P', 'powierzchnia części prawobrzeżnej', 'km²'],
                A,
            ],
            unit: '–',
            meaning: '0 – zlewnia symetryczna względem cieku głównego; wartość dodatnia – przewaga części lewobrzeżnej, ujemna – prawobrzeżnej.\nW Hydrografie współczynnik nie jest obecnie liczony – pole pozostaje puste.',
            sources: 'Radczuk 2008; Flerko i Valova 2015',
        },
        hypsometric_integral: {
            title: 'Całka hipsometryczna',
            symbol: 'HI',
            definition: 'Pole pod krzywą hipsometryczną (wykres powyżej; Strahler 1952); Hydrograf liczy ją jako względne położenie średniej wysokości zlewni między wysokością minimalną a maksymalną – to wyrażenie jest jej równoważne (Pike i Wilson 1971).',
            formula: f`HI = \frac{H_{śr} - H_{min}}{H_{max} - H_{min}}`,
            variables: [H_MEAN, H_MIN, H_MAX],
            unit: '–',
            meaning: 'Opisuje rozkład powierzchni zlewni względem wysokości: bliska 1 – większość powierzchni leży wysoko, bliska 0 – większość leży nisko, blisko wysokości ujścia. Strahler wiązał ją ze stadium rozwoju rzeźby (umownie: powyżej 0,6 – młodociane, 0,35–0,6 – dojrzałe, poniżej 0,35 – faza ostańców). W badaniach modelowych zlewnie o krzywej wypukłej (wysokie $HI$) dawały więcej odpływu, głównie podpowierzchniowego, a wklęsłe – mniej, z większym udziałem spływu powierzchniowego.\nW Hydrografie $HI$ nie wchodzi do obliczeń hydrogramu; jej licznik $H_{śr} - H_{min}$ to deniwelacja w metodzie Giandottiego.',
            sources: 'Strahler 1952; Pike i Wilson 1971; Vivoni i in. 2008',
        },

        // ── Sieć rzeczna ───────────────────────────────────────────────
        drainage_density_km_per_km2: {
            title: 'Gęstość sieci rzecznej',
            symbol: 'D_d',
            definition: 'Łączna długość cieków na jednostkę powierzchni zlewni. Liczone są tylko odcinki sieci z NMT zgodne z ciekami BDOT10k.',
            formula: f`D_d = \frac{∑ l_j}{A}`,
            variables: [['l_j', 'długość j-tego odcinka sieci zgodnego z BDOT10k', 'km'], A],
            unit: 'km/km²',
            meaning: 'Gęstsza sieć oznacza krótszą drogę wody po stokach do koryta – średnia długość spływu po stoku to ok. $1/(2 D_d)$ – a więc szybszy odpływ; w polskiej formule opadowej gęstość sieci wyznacza długość stoków i czas spływu po nich, a w badaniach wezbrania rosły z gęstością sieci.\nW Hydrografie $D_d$ nie wchodzi do obliczeń hydrogramu; wchodzi tylko do liczby chropowatości $R_n$.',
            note: 'Odcinek jest zgodny z BDOT10k, gdy co najmniej 50% jego długości leży nie dalej niż 25 m od cieku BDOT10k; 0 – brak takich odcinków. Horton i metodyka KZGW wliczają także cieki okresowe i suche doliny, więc $D_d$ z samych cieków BDOT10k jest zwykle niższa. Wynik zależy od progu sieci cieków.',
            sources: 'Horton 1945; Carlston 1963; Patton i Baker 1976; KZGW 2017; Tarboton i in. 1991',
        },
        stream_frequency_per_km2: {
            title: 'Częstość cieków',
            symbol: 'F_s',
            definition: 'Liczba odcinków cieków na jednostkę powierzchni zlewni (Horton 1945); liczone są odcinki sieci z NMT zgodne z BDOT10k.',
            formula: f`F_s = \frac{N}{A}`,
            variables: [['N', 'liczba odcinków zgodnych z BDOT10k; odcinek kończy się na połączeniu cieków lub zmianie rzędu', '–'], A],
            unit: '1/km²',
            meaning: 'Opisuje rozczłonkowanie sieci; rośnie mniej więcej z kwadratem gęstości sieci ($F_s ≈ 0,694 D_d^2$, Melton 1958), więc niesie podobną informację o potencjale szybkiego odpływu.\nW Hydrografie $F_s$ nie wchodzi do obliczeń hydrogramu.',
            note: 'W literaturze liczy się cieki według rzędów, a nie odcinki między połączeniami, więc $F_s$ z Hydrografu jest wyższa i nie jest wprost porównywalna. Liczba odcinków zależy od progu sieci, więc zlewnie warto porównywać przy tym samym progu.',
            sources: 'Horton 1945; Melton 1958 (za Hooshyar i in. 2019); Strahler 1957',
        },
        ruggedness_number: {
            title: 'Liczba chropowatości',
            symbol: 'R_n',
            definition: 'Iloczyn gęstości sieci rzecznej i deniwelacji zlewni wyrażonej w kilometrach (ang. ruggedness number, Strahler 1958).',
            formula: f`R_n = D_d · \frac{H_{max} - H_{min}}{1000}`,
            variables: [['D_d', 'gęstość sieci rzecznej', 'km/km²'], H_MAX, H_MIN],
            unit: '–',
            meaning: 'Duża wartość – zlewnia jednocześnie stroma i gęsto pocięta ciekami; zlewnie skłonne do gwałtownych wezbrań mają zwykle większe $R_n$, choć zależność nie jest uniwersalna.\nW Hydrografie $R_n$ nie wchodzi do obliczeń hydrogramu.',
            sources: 'Strahler 1958 (za Carlston 1963); Patton i Baker 1976; Carlston 1963',
        },
        max_strahler_order: {
            title: 'Maksymalny rząd cieku wg Strahlera',
            definition: 'Najwyższy rząd wśród odcinków sieci zgodnych z BDOT10k. Odcinki źródłowe mają rząd 1; połączenie dwóch cieków rzędu $n$ daje rząd $n + 1$, a połączenie cieków różnych rzędów zachowuje wyższy (Strahler 1957).',
            unit: '–',
            meaning: 'Rząd rośnie z wielkością zlewni, koryta i przepływu; w geomorfologicznym hydrogramie chwilowym szczyt zależy od stosunków Hortona i długości cieku najwyższego rzędu.\nW Hydrografie rząd nie wchodzi do obliczeń hydrogramu. Jest liczony w sieci z NMT przy bieżącym progu – gęstsza sieć (niższy próg) daje wyższe rzędy.',
            note: 'Brak wartości – w zlewni nie ma odcinków zgodnych z BDOT10k.',
            sources: 'Strahler 1957; Horton 1945; Rodríguez-Iturbe i in. 1979',
        },
        bdot_coverage: {
            title: 'Pokrycie cieku głównego przez BDOT10k',
            symbol: 'p_{BDOT}',
            definition: 'Udział cieku głównego (liczonego od ujścia) pokrytego ciekami BDOT10k.',
            formula: f`p_{BDOT} = 100 · \frac{L_{BDOT}}{L_g}`,
            variables: [['L_{BDOT}', 'część cieku głównego zgodna z BDOT10k', 'km'], L_G],
            unit: '%',
            meaning: 'Pokazuje, jaka część cieku głównego z NMT ma odpowiednik w BDOT10k. Podział drogi wody na stok i koryto zmienia czas koncentracji: spływ po stoku jest wolniejszy niż korytem, a wzór Kerby’ego opracowano dla dróg spływu po stoku do ok. 0,37 km.\nW Hydrografie to wartość informacyjna – nie wchodzi do obliczeń $T_c$ ani hydrogramu. W metodzie Kerby-Kirpich stok od koryta oddziela sieć cieków z NMT („Spływ powierzchniowy – długość”), a nie BDOT10k.',
            sources: 'Roussel i in. 2005; USDA-SCS 1986 (TR-55)',
        },

        // ── Sieć zlewni ────────────────────────────────────────────────
        'network-headwater': {
            title: 'Zlewnia górna',
            definition: 'Element sieci zlewni: zlewnia rzeki głównej powyżej najwyższego węzła na niej – zbiegu z dopływem, na którym leży punkt, albo punktu na tej rzece (np. wodowskazu). Rzeka główna punktu, powyżej którego leżą inne punkty (także przekroju zamykającego A), biegnie od niego w górę, na każdym rozwidleniu w stronę dopływu o większej powierzchni zlewni – jak ciek główny zlewni. Zlewnia górna kończy się tuż nad zbiegiem albo w punkcie.',
            meaning: 'Zlewnia cząstkowa (w HEC-HMS element „subbasin”) przekształca opad w hydrogram odpływu w swoim ujściu: odejmuje straty i liczy odpływ. Fala zlewni górnej płynie potem w dół sieci – odcinki przesuwają ją w czasie i spłaszczają – a w węzłach dodają się do niej dopływy; szczyt w przekroju A zależy od tego, jak te fale nałożą się w czasie.\nW Hydrografie zlewnia górna dostaje parametry wyznaczonej zlewni (powierzchnia, CN, pokrycie terenu, grupy glebowe, morfometria, wagi PMAXTP), zmierzone z jej własnych komórek. Do Hydrologa trafia jako zlewnia cząstkowa z modelem odpływu SCS-CN w domyślnych ustawieniach Hydrologu; hydrogramy elementów i całej sieci liczy Hydrolog.',
            note: 'Swoją rzekę główną ma każdy punkt, powyżej którego leżą inne punkty – także punkt na dopływie – więc sieć może mieć kilka zlewni górnych.',
            sources: 'USACE 2000 (HEC-HMS); USDA-NRCS 2014 (NEH 630-17); KZGW 2017',
        },
        'network-tributary': {
            title: 'Dopływ',
            definition: 'Element sieci zlewni: zlewnia punktu na dopływie – poza rzeką główną najbliższego punktu poniżej – gdy powyżej niego nie ma innych punktów. Punkt leżący najwyżej 50 m (wzdłuż spływu) nad zbiegiem z tą rzeką przenosi się do ujścia dopływu: zlewnia dopływu kończy się wtedy tuż nad zbiegiem i wpływa do węzła na zbiegu bezpośrednio. Zlewnia punktu położonego wyżej kończy się w punkcie, a od niego do węzła na zbiegu biegnie odcinek z własnym przyrzeczem.',
            meaning: 'W węźle hydrogram dopływu dodaje się do fali rzeki głównej. Szczyt poniżej zbiegu zależy od tego, jak w czasie nałożą się szczyty obu fal, a to zależy od czasu przepływu fal przez odcinki.\nW Hydrografie dopływ dostaje parametry wyznaczonej zlewni, zmierzone z jego własnych komórek; punkt przeniesiony do ujścia ma dopisek „przy ujściu dopływu”. Do Hydrologa dopływ trafia jako zlewnia cząstkowa z modelem odpływu SCS-CN, opisana jako „Dopływ do punktu …”, a po przeniesieniu do ujścia – „Dopływ do ujścia przy …”.',
            note: 'Próg 50 m odpowiada dokładności kliknięcia przy powiększeniu, w którym widać cieki: bez przeniesienia kliknięcie przy ujściu dawałoby odcinek długości kilku metrów i przyrzecze z kilku komórek. Punkt na rzece głównej (np. wodowskaz tuż nad zbiegiem) zostaje na miejscu i dostaje krótki odcinek. Najpierw każdy punkt przesuwa się do najbliższej komórki cieku w promieniu 100 m, a dopiero potem sprawdza się jego odległość od zbiegu.',
            sources: 'USACE 2000 (HEC-HMS); USDA-NRCS 2014 (NEH 630-17)',
        },
        'network-intermediate': {
            title: 'Przyrzecze',
            definition: 'Element sieci zlewni: obszar, z którego woda spływa do odcinka rzeki między jego końcami – zlewnia dolnego końca odcinka bez elementów, które wpływają do jego górnego końca (zlewni górnej, dopływów, wyższych odcinków z ich przyrzeczami). Należą do niego m.in. dopływy bez punktów, uchodzące do odcinka. Każdy odcinek ma swoje przyrzecze, poza odcinkiem między dwiema sąsiednimi komórkami NMT.',
            meaning: 'Przyrzecze to dopływ boczny odcinka, rozłożony wzdłuż niego. W modelach NRCS (WinTR-20) dopływ boczny nie wchodzi do równań trasowania – dodaje się go na górnym albo dolnym końcu odcinka; dodany na dolnym końcu omija przesunięcie i spłaszczenie fali w odcinku.\nW Hydrografie przyrzecze wpływa bezpośrednio do węzła na dolnym końcu odcinka, obok odpływu z odcinka. Jego najdłuższa droga spływu, z której Hydrolog liczy czas koncentracji (domyślnie metodą Kirpicha), jest mierzona w jego granicach i kończy się u dolnego końca odcinka. Przyrzecze dostaje parametry wyznaczonej zlewni, zmierzone z jego komórek; powierzchnie wszystkich elementów sumują się co do komórki do powierzchni zlewni przekroju A.',
            note: 'Ciek główny przyrzecza, od którego zależą jego długość i spadek cieku głównego, biegnie w górę jego odcinka.',
            sources: 'USDA-NRCS 2014 (NEH 630-17); Ponce 2014; USACE 2000 (HEC-HMS)',
        },
        reach_length_km: {
            title: 'Długość odcinka',
            symbol: 'L_o',
            definition: 'Długość odcinka rzeki od górnego do dolnego końca: różnica odległości spływu jego końców do ujścia obszaru danych, liczonych po kierunkach spływu z NMT. To długość linii odcinka na mapie – łamanej przez środki jego komórek. Kierunki spływu wyznaczono z NMT z wpalonymi ciekami BDOT10k, więc tam, gdzie jest ciek BDOT10k, linia odcinka biegnie wzdłuż niego.',
            formula: f`L_o = \frac{d_g - d_d}{1000}`,
            variables: [
                ['d_g', 'odległość spływu z komórki górnego końca odcinka do ujścia obszaru danych', 'm'],
                ['d_d', 'odległość spływu z komórki dolnego końca odcinka do ujścia obszaru danych', 'm'],
            ],
            unit: 'km',
            meaning: 'W metodzie Muskingum–Cunge długość odcinka wyznacza czas przepływu fali ($K = L_o/c$, gdzie $c$ – prędkość fali), a razem z przekrojem – objętość wody magazynowanej w odcinku: dłuższy odcinek opóźnia szczyt i bardziej go spłaszcza.\nW Hydrografie to długość odcinka przekazywana do Hydrologa (metoda Muskingum–Cunge). Hydrograf nie trasuje fali: przekrój odcinka (n Manninga, szerokość) podaje się w Hydrologu, w sekcji „Sieć i trasowanie”, przed obliczeniem sieci.',
            note: 'Na rzece meandrującej koryto bywa znacznie dłuższe od doliny, a w trasowaniu dłuższe koryto to więcej wody w odcinku i większe spłaszczenie fali. Długość zależy więc od tego, czy linia odcinka biegnie korytem – sprawdza to „Długość wzdłuż BDOT10k”.',
            sources: 'Ponce 2014; USDA-NRCS 2014 (NEH 630-17); USACE 2000 (HEC-HMS)',
        },
        reach_slope_m_per_m: {
            title: 'Spadek odcinka',
            symbol: 'I_o',
            definition: 'Różnica wysokości NMT w komórkach górnego i dolnego końca odcinka podzielona przez jego długość (źródło „NMT”). Gdy wysokość na dolnym końcu nie jest niższa niż na górnym albo na którymś końcu brak danych NMT, przyjmuje się spadek minimalny 0,0001 m/m, czyli 0,1‰ (źródło „minimalny”).',
            formula: f`I_o = \frac{H_g - H_d}{1000 · L_o}`,
            variables: [
                ['H_g', 'wysokość NMT w komórce górnego końca odcinka', 'm n.p.m.'],
                ['H_d', 'wysokość NMT w komórce dolnego końca odcinka', 'm n.p.m.'],
                ['L_o', 'długość odcinka', 'km'],
            ],
            unit: 'm/m (w panelu w ‰)',
            meaning: 'W metodzie Muskingum–Cunge spadek odcinka (spadek tarcia, przybliżany spadkiem dna) razem z przekrojem i szorstkością wyznacza prędkość fali i jej spłaszczanie: dyfuzyjność hydrauliczna $Q/(2 T S_0)$ ($Q$ – przepływ, $T$ – szerokość zwierciadła, $S_0$ – spadek) rośnie, gdy spadek maleje. Na łagodnym odcinku fala płynie więc wolniej i bardziej się spłaszcza, na stromym – szybciej i prawie bez spłaszczenia.\nW Hydrografie to spadek odcinka przekazywany do Hydrologa (metoda Muskingum–Cunge). Spadek minimalny wynika stąd, że Hydrolog nie przyjmuje spadku, który nie jest dodatni; panel sieci pokazuje wtedy uwagę z listą takich odcinków.',
            note: 'Spadek liczy się z dwóch komórek NMT na końcach odcinka, a nie jako spadek wyrównany całego odcinka. Wysokości pochodzą z NMT bez wpalenia cieków i wypełnienia zagłębień: NMT z wypełnionymi zagłębieniami jest na ciekach BDOT10k obniżony o 2 m, co przy jednym końcu na takim cieku zmieniłoby różnicę wysokości o 2 m. Gdy spadek wzdłuż rzeki wyraźnie się zmienia, według HEC-HMS może być potrzebnych kilka odcinków o różnych spadkach – odcinek dzieli punkt postawiony na rzece głównej (np. wodowskaz).',
            sources: 'Ponce 2014; USACE 2000 (HEC-HMS); USDA-NRCS 2014 (NEH 630-17)',
        },
        reach_vector_length_km: {
            title: 'Długość odcinka wzdłuż cieków BDOT10k',
            symbol: 'L_{o,BDOT}',
            definition: 'Kontrolna długość odcinka mierzona wzdłuż linii cieków BDOT10k (rzek i strumieni, kanałów, rowów). Linię odcinka z NMT próbkuje się co 10 m od górnego końca i w dolnym końcu; każdą próbkę przypisuje się do najbliższej linii BDOT10k w promieniu 25 m. Długość to suma odległości między kolejnymi próbkami: wzdłuż linii, gdy obie trafiły na tę samą, a gdy na różne – między ich rzutami na te linie.',
            formula: f`L_{o,BDOT} = \frac{1}{1000} ∑_{k=1}^{n-1} s_k`,
            variables: [
                ['s_k', 'odległość między k-tą a następną próbką: wzdłuż wspólnej linii BDOT10k albo między rzutami próbek na ich linie', 'm'],
                ['n', 'liczba próbek', '–'],
            ],
            unit: 'km',
            meaning: 'Długość odcinka decyduje o czasie przepływu fali i jej spłaszczeniu („Długość odcinka”); zwykle szacuje się ją w GIS, a do dokładnego wyznaczenia mogą być potrzebne pomiary terenowe. Długość wzdłuż linii cieków BDOT10k pozwala sprawdzić, czy linia odcinka z NMT biegnie korytem.\nW Hydrografie to wartość kontrolna: Hydrolog dostaje długość z odległości spływu („Długość odcinka”), a długość wzdłuż BDOT10k jest w przekazaniu tylko informacją o pochodzeniu odcinka.',
            note: 'Brak wartości – co najmniej jedna próbka nie ma linii BDOT10k w promieniu 25 m (odcinek biegnie przerwą w liniach albo ciekiem, którego nie ma w BDOT10k) albo przy odcinku nie ma żadnej linii. Linia z NMT biegnie po środkach komórek w ośmiu kierunkach, więc bywa nieco dłuższa od linii wektorowej (prosta ukośna – do ok. 8%); na Kamienniku długości kontrolne wyszły o 4–6% krótsze od długości odcinków. Wskazówka do odczytu: w kryteriach odbioru sieci (plan wdrożenia) długość kontrolna, gdy jest, ma się mieścić w 15% długości odcinka.',
            sources: 'USACE 2000 (HEC-HMS); USDA-NRCS 2014 (NEH 630-17)',
        },

        // ── Hietogram: formularz ───────────────────────────────────────
        'hydro-duration': {
            title: 'Czas trwania opadu',
            symbol: 'D',
            definition: 'Czas trwania opadu projektowego. Wysokość opadu $P$ dla wybranych $D$ i $p$ to kwantyl opadu maksymalnego z atlasu PMAXTP (IMGW-PIB), uśredniony w zlewni metodą wieloboków równego opadu (Thiessena): każdy punkt siatki danych PMAXTP waży tyle, jaką część zlewni zajmuje jego wielobok – obszar bliższy temu punktowi niż innym.',
            formula: f`P = \frac{1}{A} ∑_{i=1}^{K} P_i A_i`,
            variables: [
                ['P_i', 'opad PMAXTP w i-tym punkcie siatki', 'mm'],
                ['A_i', 'pole wieloboku i-tego punktu wewnątrz zlewni', 'km²'],
                ['A', 'powierzchnia zlewni', 'km²'],
                ['K', 'liczba punktów, których wieloboki obejmują zlewnię', '–'],
            ],
            unit: 'min lub h (od 5 min do 72 h)',
            meaning: 'Dłuższy opad ma większą sumę, ale mniejsze średnie natężenie; $Q_{max}$ zależy od obu, a krytyczny czas trwania – dający największe wezbranie – nie jest znany z góry (wg DVWK zwykle między $T_c$ a $2 T_c$), dlatego warto porównać kilka czasów trwania.\nW Hydrografie hietogram dzieli opad na $n = D/Δt$ kroków po 5 min.',
            sources: 'IMGW-PIB 2022 (PMAXTP); KZGW 2017; DVWK 1984 (za KZGW 2017)',
            note: 'PMAXTP podaje opady punktowe; Hydrograf uśrednia je w zlewni, ale sam nie redukuje ich do opadu obszarowego – KZGW 2017 uznaje opad punktowy za reprezentatywny do ok. 10 km², a dla zlewni 10–100 km² podaje redukcję do 10% (DVWK). Własny współczynnik redukcji możesz wpisać w polu „Współczynnik redukcji obszarowej (własny)”. Bez granicy zlewni (żądanie API z własną morfometrią bez pmaxtp_grid) opad jest interpolowany w punkcie z 4 najbliższych punktów siatki metodą odwrotnych odległości (IDW, potęga 2).',
        },
        'hydro-arf': {
            title: 'Współczynnik redukcji obszarowej (własny)',
            symbol: 'ARF',
            definition: 'Twój własny mnożnik opadu PMAXTP, przeliczający średnią opadów punktowych na opad obszarowy. Pole puste (domyślnie) – bez redukcji. Hydrograf nie wylicza tego współczynnika ani nie stosuje żadnego wzoru domyślnego: wartość i jej uzasadnienie (krzywa redukcyjna, źródło) są po stronie użytkownika.',
            formula: f`P = ARF · P_{PMAXTP}`,
            variables: [
                ['P_{PMAXTP}', 'opad PMAXTP: średnia w zlewni albo IDW w punkcie', 'mm'],
                ['ARF', 'współczynnik redukcji obszarowej, 0 < ARF ≤ 1', '–'],
            ],
            unit: '– (0 < ARF ≤ 1)',
            meaning: 'Opad punktowy jest reprezentatywny tylko dla małych zlewni, do ok. 10 km²; dla większych opad obszarowy jest mniejszy – redukcja rośnie z powierzchnią zlewni i maleje z czasem trwania opadu, a dla zlewni 10–100 km² nie przekracza 10%.\nW Hydrografie $P$ jest sumą hietogramu i wchodzi do bilansu SCS-CN; bilans pokazuje wtedy wiersz „Redukcja obszarowa” z wysokością przed redukcją, a współczynnik trafia do eksportu i do przekazania do Hydrologa.',
            note: 'Nie dotyczy własnej serii opadu.',
            sources: 'KZGW 2017; DVWK 1984 (za KZGW 2017); Chow i in. 1988 (za KZGW 2017)',
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
            meaning: 'Mniejsze $p$ – rzadszy i wyższy opad, a przy tych samych założeniach większy odpływ; np. $p = 1 %$ odpowiada $T = 100$ lat. Hydrogramowi przypisuje się to samo $p$ co opadowi – to założenie metodyki, bo opad stuletni nie zawsze wywołuje wezbranie stuletnie.\nW Hydrografie $p$ wybiera kwantyl opadu PMAXTP.',
            sources: 'IMGW-PIB 2022 (PMAXTP); KZGW 2017; USGS 2018',
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
                    ['DVWK (Euler II)', 'bloki naprzemienne: największy w 1/3 czasu trwania, kolejne – malejąco jak $w_r = r^{-0,7}$ ($r$ – ranga) – na przemian przed nim i po nim'],
                    ['Blokowy', 'stałe natężenie, $w_i = 1$'],
                ],
            },
            meaning: 'Przy tej samej sumie i czasie trwania rozkład natężenia zmienia wysokość i czas kulminacji: opad efektywny SCS-CN liczy się od sumy narastającej, więc ten sam blok opadu daje więcej odpływu, gdy spada później (straty $I_a$ są już pokryte). Polska metodyka (za DVWK 1984) zaleca deszcz z maksimum w środku czasu trwania.\nW Hydrografie przy własnej serii opadu rozkład nie jest używany.',
            note: '„DVWK (Euler II)” w Hydrologu jest przybliżeniem hietogramu Eulera typu II: wagi bloków nie pochodzą z lokalnej krzywej wysokość–czas trwania, tylko z zaniku $r^{-0,7}$, a bloki są ułożone naprzemiennie – w Eulerze II kolejne co do wielkości bloki wypełniają czas przed szczytem, a pozostałe leżą po nim. Rozkład DVWK z polskiej metodyki (maksimum w środku czasu trwania) to inny hietogram.',
            sources: 'Chow i in. 1988; KZGW 2017; Malitz 2009; Wachulec i in. 2016',
        },
        'hydro-alpha': {
            title: 'Parametr α rozkładu Beta',
            symbol: 'α',
            definition: 'Parametr kształtu rozkładu Beta; razem z $β$ ustala, kiedy w czasie trwania wypada szczyt opadu.',
            formula: BETA_PEAK.formula,
            variables: BETA_PEAK.variables,
            unit: '–',
            meaning: 'Położenie szczytu natężenia zmienia odpływ: wczesny szczyt ($α < β$) pada na zlewnię, w której straty nie są jeszcze pokryte, więc kulminacja jest zwykle niższa i wcześniejsza; późny ($α > β$) daje wyższą i późniejszą. Przy $α = β$ opad jest symetryczny.\nW Hydrografie domyślnie $α = 2$, $β = 5$: szczyt w 0,2 czasu trwania.',
            note: 'Dozwolony zakres: $0 < α ≤ 20$. Wzór na położenie szczytu dotyczy $α, β > 1$; przy $α ≤ 1 < β$ największe natężenie jest na początku opadu, przy $β ≤ 1 < α$ – na końcu.',
            sources: 'Chow i in. 1988; Wachulec i in. 2016',
        },
        'hydro-beta': {
            title: 'Parametr β rozkładu Beta',
            symbol: 'β',
            definition: 'Parametr kształtu rozkładu Beta; razem z $α$ ustala, kiedy w czasie trwania wypada szczyt opadu.',
            formula: BETA_PEAK.formula,
            variables: BETA_PEAK.variables,
            unit: '–',
            meaning: 'Większe $β$ przy tym samym $α$ przesuwa szczyt bliżej początku opadu; przy tym samym stosunku $α : β$ większe wartości obu parametrów zmniejszają rozrzut opadu w czasie, a gdy szczyt leży wewnątrz opadu (np. $α, β ≥ 2$), zwiększają też największe natężenie. Przy $α = β$ opad jest symetryczny.\nW Hydrografie domyślnie $β = 5$.',
            note: 'Dozwolony zakres: $0 < β ≤ 20$.',
        },
        'hydro-amc': {
            title: 'Uwilgotnienie początkowe (AMC)',
            definition: 'Stan zlewni przed opadem wg SCS (w nowszych wydaniach NRCS – ARC): I – suche, II – przeciętne (domyślnie; dla niego podawane są wartości CN), III – mokre. CN zlewni, podany dla AMC II, jest przeliczany:',
            formula: [
                f`CN_{\text{I}} = \frac{CN}{2,281 - 0,01281 · CN}`,
                f`CN_{\text{III}} = \frac{CN}{0,427 + 0,00573 · CN}`,
            ],
            variables: [['CN', 'CN zlewni dla AMC II', '–']],
            meaning: 'Ten sam opad może dać kilkakrotnie różny odpływ: w przykładzie NEH 630 (P = 109 mm, CN 74) odpływ wynosi 16,5 mm przy AMC I, 46 mm przy AMC II i 76 mm przy AMC III. AMC III podnosi CN (mniejsza retencja, większy odpływ), AMC I go obniża; np. CN 78,3 daje 61 przy AMC I i 89 przy AMC III.\nW Hydrografie przeliczony CN zmienia straty i opad efektywny, a przez nie cały hydrogram; $T_c$ metody NRCS jest liczony z CN dla AMC II.',
            note: 'Wzory Hawkinsa i in. (1985) przybliżają tabelę przeliczeń NEH 630 i są zalecane dla CN 55–95; Hydrolog stosuje je dla każdego CN, a wynik zaokrągla do liczby całkowitej i ogranicza do 1–100.',
            sources: 'Hawkins i in. 1985 (za Ponce i Hawkins 1996); USDA-NRCS 2004 (NEH 630-10)',
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
            meaning: 'Własna seria, np. z deszczomierza, daje hydrogram konkretnego zdarzenia – bez przypisanego prawdopodobieństwa – i zachowuje rzeczywisty rozkład natężenia, który obok sumy i czasu trwania decyduje o kulminacji.\nW Hydrografie seria zastępuje czas trwania, prawdopodobieństwo i rozkład opadu PMAXTP; hydrogram jest liczony z krokiem $Δt$ serii, a straty SCS-CN i przeliczenie AMC działają tak samo jak dla opadu PMAXTP.',
            note: 'Wartości to wysokości opadu w kroku [mm], a nie natężenia [mm/h]. „Wczytaj z bieżącego hietogramu” przenosi do tabeli ostatni hietogram PMAXTP.',
            sources: 'KZGW 2017',
        },

        // ── Hietogram: wyniki ──────────────────────────────────────────
        total_precip_mm: {
            title: 'Opad całkowity',
            symbol: 'P',
            definition: 'Suma opadu we wszystkich krokach hietogramu: wysokość z PMAXTP albo suma własnej serii opadu.',
            formula: f`P = ∑_{i=1}^{n} P_i`,
            variables: [['P_i', 'opad w i-tym kroku', 'mm'], ['n', 'liczba kroków', '–']],
            unit: 'mm',
            meaning: 'W metodzie SCS-CN objętość odpływu zależy tylko od sumy opadu i CN – natężenie nie jest uwzględniane: poniżej strat $I_a$ odpływu nie ma, powyżej opad efektywny rośnie szybciej niż proporcjonalnie do $P$. Rozkład opadu w czasie decyduje o przebiegu przyrostów $P_e$, a więc o kształcie i kulminacji fali.\nW Hydrografie z sumy narastającej $P$ liczony jest krok po kroku opad efektywny $P_e$.',
            sources: 'USDA-NRCS 2004 (NEH 630-10); USDA-SCS 1986 (TR-55)',
        },
        pmaxtp_interpolation: {
            title: 'Opad PMAXTP: skąd wysokość',
            definition: 'Jak wysokość opadu PMAXTP powstała z punktów siatki danych (kwantyle atlasu PMAXTP IMGW-PIB co 2 km). „Średnia w zlewni”: średnia ważona metodą wieloboków równego opadu (Thiessena) – wagą punktu jest część zlewni, która leży bliżej niego niż innych punktów; liczba to punkty, których wieloboki obejmują zlewnię. „W punkcie (IDW)”: interpolacja w klikniętym punkcie z 4 najbliższych punktów, gdy granica zlewni nie jest znana (żądanie API z własną morfometrią).',
            formula: [f`P = \frac{1}{A} ∑_{i=1}^{K} P_i A_i`, f`P = \frac{∑ P_i / d_i^2}{∑ 1 / d_i^2}`],
            variables: [
                ['P_i', 'opad PMAXTP w i-tym punkcie siatki', 'mm'],
                ['A_i', 'pole wieloboku i-tego punktu wewnątrz zlewni', 'km²'],
                ['A', 'powierzchnia zlewni', 'km²'],
                ['d_i', 'IDW: odległość punktu siatki od klikniętego punktu', 'm'],
            ],
            meaning: 'Do modelu opad–odpływ potrzebny jest opad średni w zlewni, a metoda wieloboków równego opadu jest jedną z dwóch najczęściej stosowanych (obok izohiet). Opad z jednego punktu jest reprezentatywny tylko dla małych zlewni, do ok. 10 km².\nW Hydrografie ta wysokość jest sumą hietogramu; punkty, ich opad i wagi pobierzesz przyciskami „Hietogram JSON” i „Punkty PMAXTP (GeoJSON)”.',
            note: 'Średnia opadów punktowych nie jest opadem obszarowym: Hydrograf sam nie stosuje współczynnika redukcji (dla zlewni 10–100 km² do 10%, DVWK); możesz wpisać własny w polu „Współczynnik redukcji obszarowej (własny)”.',
            sources: 'KZGW 2017; IMGW-PIB 2022 (PMAXTP); DVWK 1984 (za KZGW 2017)',
        },
        'rain-export': {
            title: 'Eksport hietogramu',
            definition: '„Hietogram CSV”: kroki hietogramu – czas od i do [min], opad, opad efektywny i opad narastający [mm]. „Hietogram JSON”: te same kroki ze scenariuszem (czas trwania, prawdopodobieństwo, typ hietogramu) i punktami PMAXTP. „Punkty PMAXTP (GeoJSON)”: punkty siatki użyte do wysokości opadu (WGS84) z opadem, wagą, polem wieloboku Thiessena w zlewni [km²] albo odległością od punktu IDW [m] i współrzędnymi PL-1992; przy średniej w zlewni także jej granica, przy IDW – punkt interpolacji.',
            meaning: 'Pozwala sprawdzić i powtórzyć obliczenie opadu projektowego poza Hydrografem, np. wczytać punkty i granicę zlewni do QGIS.\nW Hydrografie pliki zawierają wartości z ostatnio policzonego hydrogramu; własna seria opadu nie ma punktów PMAXTP. Z własnym współczynnikiem redukcji kroki hietogramu są już zredukowane, JSON i GeoJSON podają współczynnik i wysokość przed redukcją, a nazwy plików kończą się na „_arf…”.',
        },
        total_effective_mm: {
            title: 'Opad efektywny',
            symbol: 'P_e',
            definition: 'Część opadu, która odpływa po odjęciu strat (metoda SCS-CN). Liczony od sumy narastającej; przyrosty w kolejnych krokach tworzą hietogram opadu efektywnego.',
            formula: f`P_e = \frac{(P - I_a)^2}{P - I_a + S}`,
            variables: [['P', 'suma opadu', 'mm'], ['I_a', 'straty początkowe', 'mm'], S],
            unit: 'mm',
            meaning: '$P_e$ to wysokość odpływu bezpośredniego: objętość fali $V = P_e·A$, a przy tym samym rozkładzie w czasie rzędne hydrogramu są proporcjonalne do $P_e$. Przy odpływie poniżej ok. 13 mm metoda SCS-CN jest mniej dokładna.\nW Hydrografie przyrosty $P_e$ są splatane z hydrogramem jednostkowym.',
            note: 'Gdy $P ≤ I_a$, $P_e = 0$ – odpływu nie ma. Liczenie przyrostów $P_e$ z sumy narastającej NEH 630 traktuje jako podejście zastępcze – równanie SCS-CN nie jest równaniem infiltracji.',
            sources: 'USDA-NRCS 2004 (NEH 630-10); USDA-SCS 1986 (TR-55); Chow i in. 1988',
        },
        runoff_coefficient: {
            title: 'Współczynnik odpływu',
            symbol: 'ψ',
            definition: 'Udział opadu efektywnego w opadzie całkowitym.',
            formula: f`ψ = \frac{P_e}{P}`,
            variables: [['P_e', 'opad efektywny', 'mm'], ['P', 'opad całkowity', 'mm']],
            unit: '–',
            meaning: 'Jaka część opadu odpływa: 0 – nic, 1 – całość. Nie jest stałą zlewni: w metodzie SCS-CN rośnie z CN, z sumą opadu (gdy $P > I_a$) i z uwilgotnieniem – w przykładzie NEH 630 wynosi 15%, 42% i 70% przy AMC I, II i III.\nW Hydrografie to wynik bilansu, $ψ = P_e/P$ – nie jest to współczynnik spływu $C$ metody racjonalnej (FAA).',
            sources: 'USDA-NRCS 2004 (NEH 630-10); WMO i UNESCO 2012',
        },
        cn_used: {
            title: 'CN użyty w obliczeniu',
            symbol: 'CN',
            definition: 'Wartość CN, z której policzono straty: CN zlewni (AMC II) albo – przy AMC I lub III – wartość przeliczona i zaokrąglona do liczby całkowitej.',
            unit: '–',
            meaning: 'To ten CN, a nie CN zlewni, wyznacza straty w liczonym zdarzeniu; różnica między nimi pokazuje wpływ przyjętego uwilgotnienia (w przykładzie NEH 630 odpływ wynosi od 36% do 165% wartości dla AMC II).\nW Hydrografie od niego zależą retencja $S$ i straty $I_a$, a więc opad efektywny i cały hydrogram.',
            note: 'Gdy zlewnia nie ma CN z pokrycia terenu, użyto CN = 75.',
            sources: 'USDA-NRCS 2004 (NEH 630-10)',
        },
        retention_mm: {
            title: 'Retencja maksymalna',
            symbol: 'S',
            definition: 'Potencjalna maksymalna retencja zlewni po rozpoczęciu odpływu (metoda SCS-CN).',
            formula: f`S = \frac{25400}{CN} - 254`,
            variables: [['CN', 'CN użyty w obliczeniu', '–']],
            unit: 'mm',
            meaning: 'Opisuje zdolność kompleksu gleba–pokrycie do zatrzymania wody i w zasadzie nie zmienia się między opadami. Im większa, tym mniejszy opad efektywny; przy bardzo dużym opadzie łączne straty dążą do $S + I_a$. Dla $CN = 100$: $S = 0$ – cały opad odpływa.\nW Hydrografie liczona z CN użytego w obliczeniu; wyznacza $I_a$ i $P_e$.',
            sources: 'USDA-NRCS 2004 (NEH 630-10); USDA-SCS 1986 (TR-55)',
        },
        initial_abstraction_mm: {
            title: 'Straty początkowe',
            symbol: 'I_a',
            definition: 'Opad zatrzymany przed początkiem odpływu: intercepcja, retencja w zagłębieniach terenu, wsiąkanie i parowanie.',
            formula: 'I_a = 0,2 · S',
            variables: [S],
            unit: 'mm',
            meaning: 'Próg opadu, poniżej którego nie ma odpływu bezpośredniego – przy małym opadzie hydrogram może być zerowy; np. dla CN 78 $I_a$ ≈ 14 mm, przy AMC I (CN 61) ≈ 32 mm, przy AMC III (CN 89) ≈ 6 mm.\nW Hydrografie $I_a = 0,2·S$ odejmuje się od sumy narastającej opadu.',
            note: 'Współczynnik 0,2 to standard NRCS (NEH 630, utrzymany w wydaniu z 2025 r.). Proponowanej wartości 0,05 (Hawkins i in. 2002; Woodward i in. 2003) NRCS nie przyjęło, a Hydrograf jej nie stosuje – wymagałaby innych wartości CN.',
            sources: 'USDA-NRCS 2004 (NEH 630-10); USDA-NRCS 2025 (NEH 630-H); USDA-SCS 1986 (TR-55); Hawkins i in. 2002; Woodward i in. 2003',
        },

        // ── Hydrogram: formularz ───────────────────────────────────────
        'hydro-uh-model': {
            title: 'Model hydrogramu jednostkowego',
            definition: 'Hydrogram jednostkowy (Sherman 1932) to hydrogram odpływu bezpośredniego z 1 mm opadu efektywnego, równomiernego na całej zlewni, w jednym kroku $Δt$; hydrogram odpływu jest splotem przyrostów opadu efektywnego z hydrogramem jednostkowym (wzór przy wyniku „Hydrogram jedn.”).',
            meaning: 'Model ustala kształt odpowiedzi zlewni – czas do szczytu i wysokość szczytu; w przykładzie NEH 630 dwie zlewnie o tej samej powierzchni 11,9 km², zwarta i wydłużona, mają szczyty hydrogramu jednostkowego 1,62 i 0,62 m³/s na 1 mm. Objętość odpływu zależy od $P_e$ i $A$, a nie od modelu. Metoda zakłada liniową i niezmienną w czasie odpowiedź zlewni – to przybliżenie.\nW Hydrografie do wyboru są modele SCS, Nasha i Snydera.',
            sources: 'Sherman 1932 (za Chow i in. 1988); Chow i in. 1988; USDA-NRCS 2007 (NEH 630-16)',
        },
        'hydro-tc-method': {
            title: 'Czas koncentracji',
            symbol: 'T_c',
            definition: 'Czas dopływu wody z hydraulicznie najdalszego punktu zlewni – tego o najdłuższym czasie dopływu, niekoniecznie najdalszego – do ujścia.',
            unit: 'min',
            meaning: 'Czas koncentracji wpływa na kształt i szczyt hydrogramu: krótszy $T_c$ – wcześniejszy i wyższy szczyt (urbanizacja zwykle skraca $T_c$). Różne metody dają dla tej samej zlewni wartości różniące się nawet kilkukrotnie.\nW Hydrografie w modelu SCS $T_c$ wyznacza opóźnienie $t_{lag} = 0,6·T_c$. W modelu Snydera $T_c$ jest liczony, ale nie zmienia hydrogramu; w modelu Nasha (metoda Lutza lub regresja) nie jest liczony.',
            note: 'Sprawdź zakres stosowalności wybranej metody.',
            sources: 'USDA-NRCS 2010 (NEH 630-15); USDA-SCS 1986 (TR-55); Grimaldi i in. 2012',
        },
        'hydro-tc-runoff-coeff': {
            title: 'Współczynnik spływu (FAA)',
            symbol: 'C',
            definition: 'Współczynnik spływu metody racjonalnej ($Q = C i A$); w metodzie FAA wyznacza czas spływu po powierzchni. Wymagany w metodzie FAA: podajesz go sam, wybierając z tabeli I wytycznych FAA (1970) wartość dla powierzchni, po której spływa woda. Hydrograf nie wylicza $C$ – ani z CN, ani z pokrycia terenu.',
            unit: '–',
            list: {
                title: 'Wartości C wg FAA (1970), tab. I',
                items: [
                    ['0,75–0,95', 'szczelne pokrycia dachów'],
                    ['0,80–0,95', 'asfaltowe nawierzchnie pasów startowych'],
                    ['0,70–0,90', 'betonowe nawierzchnie pasów startowych'],
                    ['0,35–0,70', 'nawierzchnie żwirowe i tłuczniowe (makadam)'],
                    ['0,40–0,65', 'grunty nieprzepuszczalne (ciężkie)*'],
                    ['0,30–0,55', 'grunty nieprzepuszczalne z darnią*'],
                    ['0,15–0,40', 'grunty słabo przepuszczalne*'],
                    ['0,10–0,30', 'grunty słabo przepuszczalne z darnią*'],
                    ['0,05–0,20', 'grunty umiarkowanie przepuszczalne*'],
                    ['0,00–0,10', 'grunty umiarkowanie przepuszczalne z darnią*'],
                ],
            },
            meaning: 'Im mniej przepuszczalna powierzchnia, tym większy $C$ i krótszy spływ po powierzchni – w metodzie FAA czas jest proporcjonalny do $1,1 - C$: wzrost $C$ z 0,3 do 0,9 skraca go czterokrotnie.\nW Hydrografie wpływa na hydrogram tylko przez $T_c$ metody FAA. Pole „C (spływ)” jest widoczne i wymagane tylko przy tej metodzie – bez wartości obliczenie nie rusza.',
            note: '* – dla spadków od 1 do 2% (przypis tab. I). Gdy woda spływa po kilku rodzajach powierzchni, FAA zaleca $C$ średni ważony ich powierzchnią. Hydrograf przyjmuje $0 < C ≤ 1$; Hydrolog ostrzega (aplikacja tego nie pokazuje) przy $C$ powyżej 0,95 – największej wartości tabeli.',
            sources: 'FAA 1970; Chow i in. 1988',
        },
        'hydro-tc-retardance': {
            title: 'Współczynnik oporu (Kerby)',
            symbol: 'N',
            definition: 'Bezwymiarowy współczynnik oporu (retardance) Kerby’ego dla spływu po stoku – podobny w idei do współczynnika Manninga, ale znacznie większy. Wymagany w metodach Kerby i Kerby-Kirpich: podajesz go sam, wybierając z tabeli Kerby’ego wartość dla powierzchni, po której spływa woda; Hydrograf nie przyjmuje wartości domyślnej.',
            unit: '–',
            list: {
                title: 'Wartości N wg Kerby’ego (1959)',
                items: [
                    ['0,02', 'gładkie powierzchnie nieprzepuszczalne (asfalt, beton)'],
                    ['0,10', 'gładka, ubita, odkryta gleba'],
                    ['0,20', 'słaba trawa, uprawy rzędowe, umiarkowanie szorstka odkryta powierzchnia'],
                    ['0,40', 'pastwisko, przeciętna trawa'],
                    ['0,60', 'las liściasty'],
                    ['0,80', 'gęsta trawa, las iglasty, las liściasty z grubą ściółką'],
                ],
            },
            meaning: 'Szorstkość spowalnia spływ po stoku: $T_c$ rośnie z $N$ w potędze 0,467 – dla $N = 0,8$ jest ok. 5,6 razy dłuższy niż dla 0,02. Wartości z tabeli przyjmuje się bez interpolacji.\nW Hydrografie wpływa na $T_c$ metod Kerby i Kerby-Kirpich (część spływu po stoku). Pole „N (opór)” jest widoczne i wymagane tylko przy tych metodach, w zakresie 0,02–0,8 – bez wartości obliczenie nie rusza.',
            sources: 'Kerby 1959 (za Fang i in. 2005, tab. 3.3); TxDOT 2019; Roussel i in. 2005',
        },
        'hydro-nash-estimation': {
            title: 'Estymacja parametrów Nasha',
            definition: 'Sposób wyznaczenia liczby zbiorników $N$ i stałej retencji $K$ kaskady Nasha.',
            meaning: '$N$ i $K$ wyznacza się metodą momentów z obserwowanych wezbrań; w zlewni bez pomiarów szacuje się je z cech zlewni i opadu, a różne metody dają różne $N$ i $K$, więc różne $Q_{max}$ i czas do szczytu.\nW Hydrografie do wyboru są metoda Lutza (domyślna) i regresja urbanizacyjna; warto porównać wyniki.',
            sources: 'Nash 1957; Chow i in. 1988',
        },
        'hydro-snyder-ct': {
            title: 'Współczynnik czasu (Snyder)',
            symbol: 'C_t',
            definition: 'Współczynnik opóźnienia w modelu Snydera (domyślnie 1,5); ujmuje wpływ spadku i retencji zlewni na opóźnienie.',
            formula: f`t_L = C_t (L_g L_c)^{0,3}`,
            variables: [L_G, L_C, ['t_L', 'opóźnienie zlewni', 'h']],
            unit: '–',
            meaning: 'Większy $C_t$ – dłuższe opóźnienie, szczyt później i niższy ($q_p$ jest odwrotnie proporcjonalny do $t_L$). Bez pomiarów $C_t$ przyjmuje się z kalibracji w zlewniach tego samego regionu.\nW Hydrografie wchodzi do opóźnienia $t_L$ hydrogramu Snydera.',
            note: '$C_t$ jest tu w postaci metrycznej ($L$ w km), równej 0,75 × $C_t$ Snydera: typowe 1,35–1,65 to przeliczone 1,8–2,2 z Appalachów, a domyślne 1,5 – typowe 2,0. W literaturze notowano $C_t$ od 0,4 w zlewniach górskich do 8,0 nad Zatoką Meksykańską (w tej postaci ok. 0,3–6).',
            sources: 'Snyder 1938 (za Chow i in. 1988); Chow i in. 1988; Young i in. 1986; USACE 2000 (HEC-HMS)',
        },
        'hydro-snyder-cp': {
            title: 'Współczynnik szczytu (Snyder)',
            symbol: 'C_p',
            definition: 'Współczynnik przepływu szczytowego w modelu Snydera (domyślnie 0,6); odzwierciedla retencję zlewni.',
            formula: f`q_p = 0,275 · C_p \frac{A}{t_L}`,
            variables: [A, ['t_L', 'opóźnienie zlewni', 'h'], ['q_p', 'przepływ szczytowy hydrogramu jednostkowego', 'm³/s na 1 mm']],
            unit: '–',
            meaning: 'W metodzie Snydera szczyt hydrogramu jednostkowego jest proporcjonalny do $C_p$: przy objętości 1 mm większy $C_p$ (mniejsza retencja) daje hydrogram wyższy i węższy.\nW Hydrografie kształt hydrogramu Snydera jest krzywą gamma ze szczytem w $t_p$, normowaną do 1 mm, więc $C_p$ zmienia szczyt tylko nieznacznie – przez długość podstawy $t_b = 0,556·A/q_p$, na której hydrogram jest obcinany.',
            note: 'Typowo 0,4–0,8 (Snyder: 0,56–0,69, za Meier 1964); mniejsze w zlewniach o dużej retencji, większe przy małej; większemu $C_p$ zwykle towarzyszy mniejszy $C_t$.',
            sources: 'Snyder 1938 (za Chow i in. 1988); Meier 1964; USACE 2000 (HEC-HMS); TxDOT 2019; Ponce 2013',
        },

        // ── Hydrogram: wyniki ──────────────────────────────────────────
        peak_discharge_m3s: {
            title: 'Przepływ maksymalny',
            symbol: 'Q_{max}',
            definition: 'Największa rzędna hydrogramu odpływu w ujściu.',
            formula: 'Q_{max} = max_k Q_k',
            variables: [['Q_k', 'przepływ w k-tym kroku hydrogramu', 'm³/s']],
            unit: 'm³/s',
            meaning: 'Główny wynik projektowy – podstawa wymiarowania budowli wodnych. Rośnie z opadem efektywnym i powierzchnią; przy tej samej objętości jest wyższy w zlewniach o szybkiej odpowiedzi (krótki czas koncentracji, zwarty kształt).\nW Hydrografie maleje przy dłuższym czasie reakcji zlewni w modelu: $T_c$ (SCS), $K$ przy stałym $N$ (Nash), $t_L$ (Snyder).',
            note: 'To odpływ bezpośredni z opadu – bez przepływu bazowego.',
            sources: 'USDA-NRCS 2007 (NEH 630-16); Chow i in. 1988',
        },
        time_to_peak_min: {
            title: 'Czas do szczytu',
            symbol: 't_p',
            definition: 'Czas od początku opadu do wystąpienia $Q_{max}$.',
            unit: 'min',
            meaning: 'Mówi, jak szybko po rozpoczęciu opadu nadchodzi szczyt; zależy od rozkładu opadu w czasie i od czasu reakcji zlewni – zlewnie o dłuższym czasie koncentracji, np. wydłużone, osiągają szczyt później (w przykładzie NEH 630: 1,5 h wobec 4,0 h przy tej samej powierzchni).\nW Hydrografie wynika z rozkładu opadu i parametrów czasowych modelu ($T_c$, $N$ i $K$, $t_L$).',
            note: 'Odczyt z siatki czasu hydrogramu – z dokładnością do kroku $Δt$.',
            sources: 'USDA-NRCS 2007 (NEH 630-16); USDA-SCS 1986 (TR-55)',
        },
        total_volume_m3: {
            title: 'Objętość odpływu',
            symbol: 'V',
            definition: 'Objętość wody odpływającej w czasie całego hydrogramu: pole pod hydrogramem.',
            formula: 'V = ∑_k Q_k · 60 Δt',
            variables: [['Q_k', 'przepływ w k-tym kroku', 'm³/s'], DT],
            unit: 'm³',
            meaning: 'Objętość odpływu bezpośredniego jest równa $P_e·A$ (1 mm z 1 km² to 1000 m³) i – obok szczytu – decyduje m.in. o potrzebnej pojemności retencji; model hydrogramu rozkłada ją tylko w czasie.\nW Hydrografie pole pod hydrogramem odpowiada $P_e·A$ z dokładnością do dyskretyzacji.',
            sources: 'Chow i in. 1988; USDA-SCS 1986 (TR-55)',
        },
        tc_method: {
            title: 'Metoda czasu koncentracji',
            definition: 'Metoda, którą policzono $T_c$ (wybór w polu „Metoda Tc”).',
            meaning: 'Wybór metody może zmienić $T_c$ kilkukrotnie, a przez to czas i wysokość szczytu hydrogramu.\nW Hydrografie metoda wpływa na hydrogram tylko w modelu SCS; w modelu Snydera $T_c$ jest liczony, ale nie zmienia hydrogramu.',
            sources: 'Grimaldi i in. 2012; Roussel i in. 2005',
        },
        tc_min: {
            title: 'Czas koncentracji',
            symbol: 'T_c',
            definition: 'Czas dopływu wody z hydraulicznie najdalszego punktu zlewni do ujścia, policzony wybraną metodą.',
            formula: 't_{lag} = 0,6 · T_c',
            variables: [['t_{lag}', 'opóźnienie zlewni: czas od środka ciężkości opadu efektywnego do szczytu odpływu (model SCS)', 'min']],
            unit: 'min',
            meaning: 'Krótszy $T_c$ oznacza szybszą reakcję zlewni – wcześniejszy i wyższy szczyt.\nW Hydrografie w modelu SCS czas do szczytu hydrogramu jednostkowego wynosi $Δt/2 + 0,6·T_c$; w modelu Snydera nie zmienia hydrogramu.',
            sources: 'USDA-NRCS 2010 (NEH 630-15); USDA-NRCS 2007 (NEH 630-16)',
        },
        uh_model: {
            title: 'Model hydrogramu jednostkowego',
            definition: 'Model użyty w obliczeniu (dla Nasha w nawiasie sposób estymacji $N$ i $K$). Hydrogram odpływu jest splotem przyrostów opadu efektywnego z hydrogramem jednostkowym $u$ – odpowiedzią zlewni na 1 mm opadu efektywnego w jednym kroku:',
            formula: 'Q_k = ∑_{i=0}^{k} P_{e,i} · u_{k-i}',
            variables: [
                ['Q_k', 'przepływ w chwili $k·Δt$ od początku opadu', 'm³/s'],
                ['P_{e,i}', 'opad efektywny w i-tym kroku (liczonym od 0)', 'mm'],
                ['u_j', 'rzędna hydrogramu jednostkowego po $j$ krokach', 'm³/s na 1 mm'],
            ],
            meaning: 'Model ustala kształt hydrogramu – czas do szczytu i wysokość szczytu; objętość odpływu zależy od opadu efektywnego i powierzchni. Splot zakłada liniową i niezmienną w czasie odpowiedź zlewni.\nW Hydrografie hydrogram jednostkowy dla kroku $Δt$ liczy Hydrolog wybranym modelem.',
            sources: 'Chow i in. 1988; USDA-NRCS 2007 (NEH 630-16)',
        },
        nash_n: {
            title: 'Liczba zbiorników kaskady Nasha',
            symbol: 'N',
            definition: 'Liczba jednakowych zbiorników liniowych w kaskadzie Nasha (może być ułamkowa).',
            formula: ['t_{lag} = N · K', 't_p = (N - 1) · K'],
            variables: [['K', 'stała retencji zbiornika', 'min'], ['t_{lag}', 'opóźnienie: środek ciężkości hydrogramu chwilowego', 'min'], ['t_p', 'czas do szczytu hydrogramu chwilowego (dla $N > 1$)', 'min']],
            unit: '–',
            meaning: '$N$ decyduje o kształcie odpowiedzi zlewni – od natychmiastowej, wykładniczo malejącej ($N = 1$) po stopniowo narastającą (większe $N$); razem z $K$ ustala opóźnienie $N·K$.\nW Hydrografie $N$ wynika z wybranej estymacji; przy stałym $K$ większe $N$ – szczyt później i niższy.',
            sources: 'Nash 1957; Chow i in. 1988',
        },
        nash_k_min: {
            title: 'Stała retencji zbiornika',
            symbol: 'K',
            definition: 'Stała retencji każdego zbiornika kaskady Nasha.',
            formula: f`u(t) = \frac{1}{K Γ(N)} (\frac{t}{K})^{N-1} e^{-t/K}`,
            variables: [['u(t)', 'rzędna hydrogramu chwilowego', '1/min'], ['N', 'liczba zbiorników', '–'], ['Γ', 'funkcja gamma', ''], ['t', 'czas od opadu', 'min']],
            unit: 'min',
            meaning: '$K$ jest skalą czasu odpowiedzi zlewni (zbiornik liniowy: retencja $S = K·Q$): przy stałym $N$ hydrogram chwilowy rozciąga się proporcjonalnie do $K$ – opóźnienie $N·K$ rośnie, a szczyt maleje jak $1/K$.\nW Hydrografie $K$ wynika z wybranej estymacji parametrów Nasha.',
            sources: 'Nash 1957; Chow i in. 1988',
        },
        nash_forest_pct: {
            title: 'Udział lasów w zlewni',
            symbol: 'W',
            definition: 'Udział powierzchni leśnych w powierzchni zlewni według pokrycia terenu (klasa „las”, tereny leśne BDOT10k PTLZ), użyty jako $W$ w metodzie Lutza.',
            formula: f`W = 100 · \frac{A_{las}}{∑ A_j}`,
            variables: [['A_{las}', 'powierzchnia lasów w zlewni', 'm²'], ['A_j', 'powierzchnia j-tej klasy pokrycia terenu w zlewni', 'm²']],
            unit: '%',
            meaning: 'Lasy wydłużają czas do szczytu hydrogramu chwilowego ($t_p ∝ e^{0,004 W}$; np. o 22% przy 50% lasów), więc szczyt jest późniejszy i niższy.\nW Hydrografie $W$ wynika z pokrycia terenu zlewni (z dokładnością do 0,1%) i wchodzi do estymacji Nasha metodą Lutza.',
            sources: 'Lutz 1984 (za KZGW 2017 i Assmann 1999); KZGW 2017',
        },
        nash_urban_pct: {
            title: 'Udział terenów zurbanizowanych w zlewni',
            symbol: 'U',
            definition: 'Udział terenów zabudowanych i komunikacyjnych w powierzchni zlewni według pokrycia terenu (klasy „zabudowa mieszkaniowa”, „zabudowa przemysłowa” i „droga” – drogi i place utwardzone; BDOT10k: zabudowa PTZB, tereny przemysłowo-składowe PTNZ, kompleksy przemysłowe KUPG, tereny komunikacyjne PTKM i place PTPL), użyty jako $U$ w metodzie Lutza.',
            formula: f`U = 100 · \frac{A_{zab} + A_{dr}}{∑ A_j}`,
            variables: [['A_{zab}', 'powierzchnia terenów zabudowanych w zlewni', 'm²'], ['A_{dr}', 'powierzchnia dróg i placów w zlewni', 'm²'], ['A_j', 'powierzchnia j-tej klasy pokrycia terenu w zlewni', 'm²']],
            unit: '%',
            meaning: 'Zabudowa skraca czas do szczytu hydrogramu chwilowego ($t_p ∝ e^{-0,016 U}$; np. o 27% przy 20% terenów zurbanizowanych), więc szczyt jest wcześniejszy i wyższy.\nW Hydrografie $U$ wynika z pokrycia terenu zlewni (z dokładnością do 0,1%) i wchodzi do estymacji Nasha metodą Lutza.',
            note: 'Drogi i place należą do terenów zurbanizowanych jak w ewidencji gruntów (grunty zabudowane i zurbanizowane obejmują tereny komunikacyjne); grunty nieużytkowane, tereny pod urządzeniami technicznymi (np. farmy fotowoltaiczne), place nieutwardzone, wyrobiska i składowiska (klasa „inny”) – nie. To inna wielkość niż $U$ regresji urbanizacyjnej (średnia nieprzepuszczalność pokrycia terenu).',
            sources: 'Lutz 1984 (za KZGW 2017 i Assmann 1999); KZGW 2017; Rozporządzenie EGiB 2021',
        },
        nash_urban_fraction: {
            title: 'Wskaźnik urbanizacji',
            symbol: 'U',
            definition: 'Średnia ważona powierzchnią nieprzepuszczalność pokrycia terenu zlewni (klasy BDOT10k), użyta jako $U$ w regresji urbanizacyjnej; pokazana w %.',
            formula: f`U = \frac{∑ A_j u_j}{∑ A_j}`,
            variables: [['A_j', 'powierzchnia j-tej klasy pokrycia terenu', 'm²'], ['u_j', 'nieprzepuszczalność tej klasy', '–']],
            unit: '– (w tabeli w %)',
            meaning: 'Udział powierzchni nieprzepuszczalnych skraca reakcję zlewni: przy $U = 0,2$ opóźnienie maleje o ok. 26%, a $k$ o ok. 11% względem zlewni bez uszczelnień – hydrogram szybszy i wyższy.\nW Hydrografie wchodzi tylko do regresji urbanizacyjnej: $t_L ∝ (1 + U)^{-1,66}$, $k ∝ (1 + U)^{-0,62}$.',
            note: 'Nieprzepuszczalność to stałe wartości przypisane w Hydrografie źródłom BDOT10k; dla zabudowy są to średnie udziały powierzchni nieprzepuszczalnych dzielnic TR-55: przemysłowej 72%, handlowo-usługowej 85%, mieszkaniowej wielorodzinnej 65% oraz jednorodzinnej i pozostałej 30%.',
            sources: 'Sarma i in. 1969; KZGW 2017; USDA-SCS 1986 (TR-55)',
        },
        nash_effective_precip_mm: {
            title: 'Opad efektywny w regresji Nasha',
            symbol: 'H',
            definition: 'Opad efektywny SCS-CN policzony z całej sumy opadu, użyty jako $H$ w regresji urbanizacyjnej.',
            formula: f`H = \frac{(P - I_a)^2}{P - I_a + S}`,
            variables: [['P', 'suma opadu', 'mm'], ['I_a', 'straty początkowe', 'mm'], S],
            unit: 'mm',
            meaning: 'W tej regresji większy opad efektywny skraca opóźnienie ($t_L ∝ H^{-0,27}$; podwojenie $H$ – o ok. 17%), więc parametry Nasha zależą nie tylko od zlewni, ale i od opadu. To własność regresji: w pomiarach na Potoku Służewieckim opóźnienie rosło z sumą opadu.\nW Hydrografie $H$ jest liczony z całej sumy opadu i z CN przeliczonego według AMC.',
            note: 'Gdy opad nie przekracza strat $I_a$, przyjmowane jest $H$ = 1 mm.',
            sources: 'Rao i in. 1972 (za Sikorska i Banasik 2010); Sikorska i Banasik 2010',
        },
        nash_duration_h: {
            title: 'Czas trwania opadu efektywnego',
            symbol: 'D',
            definition: 'Czas, w którym przyrost opadu efektywnego jest dodatni: liczba takich kroków hietogramu razy krok $Δt$.',
            formula: 'D = n_e · Δt',
            variables: [['n_e', 'liczba kroków z dodatnim opadem efektywnym', '–'], DT],
            unit: 'h (pokazany też w min)',
            meaning: 'Przy tej samej objętości dłuższy opad efektywny daje późniejszy i niższy szczyt: w regresji opóźnienie rośnie jak $D^{0,37}$, a $k$ jak $D^{0,22}$.\nW Hydrografie $D$ to liczba kroków z dodatnim przyrostem opadu efektywnego razy $Δt$ – przy opadzie z przerwami kroki bez opadu efektywnego są pomijane.',
            sources: 'Sarma i in. 1969; KZGW 2017',
        },

        // ── Zakres stosowalności: modele UH ────────────────────────────
        'hydro-uh-model:scs': {
            summary: 'Standardowy hydrogram NRCS (NEH 630); zalecany dla jednorodnych zlewni do ok. 52 km²; Hydrolog nie sprawdza zakresu.',
            title: 'SCS (NRCS) – bezwymiarowy hydrogram jednostkowy',
            definition: 'Kształt z tablicy NRCS ($q/q_p$ od $t/t_p$, do $5 t_p$; Mockus 1957), skalowany czasem do szczytu $t_p$ i przepływem szczytowym $q_p$.',
            formula: [f`t_{lag} = 0,6 · T_c`, f`t_p = \frac{Δt}{2} + t_{lag}`, f`q_p = 0,208 · \frac{A}{t_p}`],
            variables: [
                TC, DT, A,
                ['t_p', 'czas do szczytu hydrogramu jednostkowego (we wzorze na $q_p$ w godzinach)', 'min'],
                ['q_p', 'przepływ szczytowy hydrogramu jednostkowego', 'm³/s na 1 mm'],
            ],
            meaning: 'Kształt hydrogramu jest stały (współczynnik szczytu 484), a szczyt rośnie jak $A/t_p$: przy tej samej powierzchni zlewnia o krótszym $T_c$ daje szczyt wyższy i wcześniejszy. NEH 630 notuje dla różnych zlewni współczynniki szczytu od poniżej 100 do ponad 600 (wyższe w terenie stromym).\nW Hydrografie jedynym parametrem czasowym zlewni jest $T_c$ (obok kroku $Δt$), więc wybór metody Tc bezpośrednio zmienia $Q_{max}$.',
            range: 'NEH 630 zaleca jednorodne podzlewnie nie większe niż ok. 52 km² (20 mi²) i krok $Δt$ nie dłuższy niż $0,25 t_p$ – przy $Δt$ = 5 min oznacza to $T_c$ od ok. 29 min. Hydrolog nie sprawdza zakresu; Hydrograf liczy jeden hydrogram dla zlewni do 250 km².',
            sources: 'Mockus 1957 (za NEH 630-16); USDA-NRCS 2007 (NEH 630-16); USDA-NRCS 2010 (NEH 630-15)',
        },
        'hydro-uh-model:nash': {
            summary: 'Kaskada $N$ zbiorników liniowych (Nash 1957); zakres zależy od sposobu estymacji $N$ i $K$.',
            title: 'Nash – kaskada zbiorników liniowych',
            definition: 'Zlewnia jako $N$ jednakowych zbiorników liniowych połączonych szeregowo, każdy o stałej retencji $K$ (Nash 1957). Hydrogram chwilowy:',
            formula: [f`u(t) = \frac{1}{K Γ(N)} (\frac{t}{K})^{N-1} e^{-t/K}`, 't_{lag} = N · K', 't_p = (N - 1) · K'],
            variables: [
                ['N', 'liczba zbiorników', '–'],
                ['K', 'stała retencji zbiornika', 'min'],
                ['Γ', 'funkcja gamma', ''],
                ['t_{lag}', 'opóźnienie (środek ciężkości hydrogramu chwilowego)', 'min'],
                ['t_p', 'czas do szczytu hydrogramu chwilowego (dla $N > 1$)', 'min'],
            ],
            meaning: 'Dwa parametry opisują opóźnienie ($N·K$) i rozmycie ($N·K^2$) odpowiedzi zlewni: przy stałym $N$ większe $K$, a przy stałym $K$ większe $N$ – hydrogram bardziej opóźniony i spłaszczony.\nW Hydrografie hydrogram jednostkowy dla kroku $Δt$ powstaje z krzywej S hydrogramu chwilowego i jest skalowany powierzchnią $A$.',
            range: 'Hydrolog nie sprawdza zakresu $N$ i $K$; ich wartości zależą od zlewni i od wybranej estymacji.',
            sources: 'Nash 1957; Chow i in. 1988',
        },
        'hydro-uh-model:snyder': {
            summary: 'Hydrogram syntetyczny (Snyder 1938; zlewnie Appalachów 26–26 000 km²); $C_t$ i $C_p$ z kalibracji regionalnej; Hydrolog nie sprawdza zakresu.',
            title: 'Snyder – syntetyczny hydrogram jednostkowy',
            definition: 'Hydrogram z empirycznych zależności od długości cieku i położenia środka ciężkości zlewni (Snyder 1938): opóźnienie $t_L$ dla opadu o standardowym czasie trwania $t_D$ i przepływ szczytowy $q_p$:',
            formula: [
                f`t_L = C_t (L_g L_c)^{0,3}`,
                f`t_D = \frac{t_L}{5,5}`,
                f`t_p = t_L + \frac{t_D}{2}`,
                f`q_p = 0,275 · C_p \frac{A}{t_L}`,
            ],
            variables: [
                ['C_t, C_p', 'współczynniki czasu (postać metryczna) i szczytu', '–'],
                L_G, L_C,
                ['t_L', 'opóźnienie zlewni', 'h'],
                ['t_D', 'standardowy czas trwania opadu', 'h'],
                ['t_p', 'czas do szczytu hydrogramu jednostkowego', 'h'],
                A,
                ['q_p', 'przepływ szczytowy hydrogramu jednostkowego', 'm³/s na 1 mm'],
            ],
            meaning: 'Im dłuższy ciek i dalej od ujścia leży środek ciężkości zlewni, tym dłuższe opóźnienie i niższy szczyt – rozmiar i kształt zlewni wchodzą tu wprost, przez $L_g$ i $L_c$.\nW Hydrografie hydrogram zależy od $A$, $L_g$, $L_c$ i $C_t$; $C_p$ wpływa słabo (kształt gamma normowany do 1 mm), a $T_c$ jest liczony, ale nie zmienia hydrogramu.',
            range: 'Metoda empiryczna Snydera (1938) dla zlewni Appalachów o powierzchni ok. 26–26 000 km²; $C_t$ i $C_p$ należy brać z kalibracji w zlewniach tego samego regionu (typowo $C_t$ = 1,35–1,65 w postaci metrycznej, $C_p$ = 0,4–0,8). Hydrolog nie sprawdza zakresu. Wymaga $L_g$ i $L_c$.',
            note: 'Metoda Snydera przelicza opóźnienie i szczyt na czas trwania opadu ($t_{LR} = t_L + 0,25(Δt - t_D)$). Hydrolog 0.6.3, z którego korzysta Hydrograf, tego nie robi: hydrogram jednostkowy jest liczony dla $t_D$ niezależnie od kroku $Δt$, więc przy $Δt < t_D$ szczyt wychodzi niższy i późniejszy (poprawione w rozwojowej wersji 1.0 Hydrologu).',
            sources: 'Snyder 1938 (za Chow i in. 1988); Chow i in. 1988; USACE 2000 (HEC-HMS); Ponce 2013',
        },

        // ── Zakres stosowalności: estymacja Nasha ──────────────────────
        'hydro-nash-estimation:from_lutz': {
            summary: 'Zlewnie niekontrolowane quasi-naturalne (uszczelnienie < 5%, do 236 km²) – KZGW 2017; wzór Lutza (1984) z 75 zlewni.',
            title: 'Metoda Lutza',
            definition: 'Parametry z cech fizjograficznych (Lutz 1984, w postaci z metodyki KZGW 2017): najpierw czas do szczytu $t_p$ i rzędna szczytu $u_p$ hydrogramu chwilowego, z nich $N$, a potem $K$.',
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
                ['n', 'współczynnik szorstkości Manninga koryta', 's·m^(−1/3)'],
                ['U, W', 'udział terenów zurbanizowanych i leśnych', '%'],
                ['t_p', 'czas do szczytu hydrogramu chwilowego', 'h'],
                ['u_p', 'rzędna szczytu hydrogramu chwilowego', '1/h'],
            ],
            meaning: 'Czas do szczytu rośnie z długością cieku i oddaleniem środka ciężkości zlewni od ujścia, maleje ze spadkiem; lasy go wydłużają, zabudowa skraca. Zlewnia wydłużona, z odległym środkiem ciężkości i małym spadkiem daje późniejszy i niższy szczyt.\nW Hydrografie: $L_g$, $L_c$ i $I_g$ z NMT, $n = 0,035$, $U$ i $W$ z pokrycia terenu zlewni (bez danych o pokryciu terenu $U = W = 0$).',
            range: 'Wg metodyki KZGW (2017) – dla niekontrolowanych zlewni quasi-naturalnych (uszczelnienie poniżej 5%) do 236 km², jako alternatywa dla modelu Snydera. Wymaga $L_g$, $L_c$ i $I_g$ oraz $L_c ≤ L_g$; $N$ jest szukane w przedziale 1,1–20, a gdy rozwiązania tam nie ma, obliczenie kończy się błędem.',
            note: 'Hydrograf przyjmuje $n = 0,035$ dla każdego cieku; $U$ to udział zabudowy, dróg i placów, a $W$ – lasów w pokryciu terenu zlewni (wiersze „Lasy W” i „Tereny zurbanizowane U” w tabeli hydrogramu). Metoda jest stosowana także w zlewniach zurbanizowanych i do 250 km².',
            sources: 'Lutz 1984 (za KZGW 2017 i Assmann 1999); KZGW 2017; Rozporządzenie EGiB 2021',
        },
        'hydro-nash-estimation:from_urban_regression': {
            summary: 'Zlewnie zurbanizowane (KZGW 2017: do 52 km²); regresja z danych z 11 zlewni w Indianie i Teksasie (0,12–50 km²).',
            title: 'Regresja urbanizacyjna (Rao, Delleur, Sarma)',
            definition: 'Regresja dla zlewni zurbanizowanych i częściowo zurbanizowanych (Sarma i in. 1969; Rao i in. 1972), w postaci metrycznej jak w metodyce KZGW 2017.',
            formula: [
                f`t_L = 1,28 · A^{0,46} (1 + U)^{-1,66} H^{-0,27} D^{0,37}`,
                f`k = 0,56 · A^{0,39} (1 + U)^{-0,62} H^{-0,11} D^{0,22}`,
                f`N = \frac{t_L}{k}`,
            ],
            variables: [
                A,
                ['U', 'udział powierzchni nieprzepuszczalnych', '–'],
                ['H', 'opad efektywny', 'mm'],
                ['D', 'czas trwania opadu efektywnego', 'h'],
                ['t_L', 'opóźnienie środka ciężkości odpływu względem środka ciężkości opadu efektywnego', 'h'],
                ['k', 'stała retencji zbiornika ($K = 60 k$ min)', 'h'],
            ],
            meaning: 'Większy udział powierzchni nieprzepuszczalnych skraca opóźnienie i zmniejsza $K$ oraz $N$ – szczyt hydrogramu chwilowego jest wyższy i wcześniejszy; parametry zależą też od opadu ($H$, $D$), więc nie są stałą cechą zlewni.\nW Hydrografie $U$ to średnia ważona nieprzepuszczalność pokrycia terenu, $H$ – opad efektywny SCS-CN z sumy opadu, $D$ – liczba kroków z opadem efektywnym razy $Δt$.',
            range: 'Równanie opóźnienia dopasowano do 125 opadów z 11 zlewni o powierzchni 0,12–50 km² i $U$ = 0–0,38 w Indianie i Teksasie (Sarma i in. 1969; w pracy z 1972 r. – ok. 200 opadów); autorzy przestrzegają przed ekstrapolacją. KZGW 2017 zaleca te wzory dla zlewni zurbanizowanych do 52 km². Hydrolog wymaga $0 ≤ U < 1$ i nie ostrzega poza zakresem kalibracji.',
            note: 'Gdy opad nie przekracza strat $I_a$, Hydrograf przyjmuje $H$ = 1 mm.',
            sources: 'Sarma i in. 1969; Rao i in. 1972; KZGW 2017',
        },

        // ── Zakres stosowalności: metody Tc ────────────────────────────
        'hydro-tc-method:nrcs': {
            summary: 'Równanie opóźnienia NRCS: CN 50–95; dane z 24 zlewni 0,005–24 km² (większość < 8 km²).',
            title: 'NRCS – równanie opóźnienia (lag)',
            definition: 'Opóźnienie zlewni z równania NRCS (Mockus 1961; NEH 630, rozdz. 15) przeliczone na czas koncentracji, $T_c = t_{lag}/0,6$. Opór powierzchni zlewni ujmuje przez CN.',
            formula: f`T_c = 0,01416 · L_{max}^{0,8} (S + 25,4)^{0,7} I_{śr}^{-0,5}`,
            variables: [
                ['L_{max}', 'najdłuższa droga spływu od punktu zlewni najdalszego hydraulicznie do ujścia', 'm'],
                S,
                ['I_{śr}', 'średni spadek terenu zlewni (nie spadek drogi spływu)', '%'],
            ],
            unit: 'min',
            meaning: 'Dłuższa droga spływu wydłuża $T_c$, a wyższy CN (gładsza, mniej retencyjna powierzchnia) i większy spadek terenu go skracają.\nW Hydrografie: $L_{max}$ („Najdłuższa droga spływu”) i $I_{śr}$ („Średni spadek terenu”) z NMT oraz CN zlewni dla AMC II. Gdy brak $L_{max}$ albo $I_{śr}$, obliczenie kończy się komunikatem o brakujących danych – bez wartości zastępczych.',
            range: 'Wg NEH 630 równania nie stosuje się dla CN poniżej 50 i powyżej 95; opracowano je na danych z 24 zlewni o powierzchni 0,005–24 km², w większości poniżej 8 km². Hydrolog zgłasza ostrzeżenie (aplikacja go nie pokazuje) poza CN 50–95 i powierzchnią 0,005–24 km².',
            sources: 'Mockus 1961 (za NEH 630-15); USDA-NRCS 2010 (NEH 630-15); Fang i in. 2005',
        },
        'hydro-tc-method:kirpich': {
            summary: 'Małe zlewnie rolnicze z wyraźnym korytem (dane: 7 zlewni w Tennessee, 0,005–0,45 km², spadki 3–10%).',
            title: 'Kirpich (1940)',
            definition: 'Wzór empiryczny dla małych zlewni rolniczych z wyraźnymi korytami; opisuje głównie czas przepływu korytem. Długość i spadek mierzy się wzdłuż drogi wody od ujścia do punktu zlewni najdalszego hydraulicznie.',
            formula: f`T_c = 3,981 · L_{max}^{0,77} · I_{dr}^{-0,385}`,
            variables: [
                L_MAX,
                ['I_{dr}', 'spadek najdłuższej drogi spływu: wysokość jej początku nad ujściem podzielona przez jej długość', 'm/m'],
            ],
            unit: 'min',
            meaning: 'Czas koncentracji zależy tylko od długości i spadku drogi wody – nie od CN ani pokrycia terenu.\nW Hydrografie: $L_{max}$ i $I_{dr}$ z NMT („Najdłuższa droga spływu” i „Spadek najdłuższej drogi spływu”). Gdy którejś wartości brak, obliczenie kończy się komunikatem o brakujących danych – spadek cieku głównego ani średni spadek terenu jej nie zastępują.',
            range: 'Dane Kirpicha: 7 małych zlewni rolniczych w Tennessee, 0,005–0,45 km², spadki 3–10%; wg autora wzór stosuje się do ok. 0,8 km² (200 akrów). Hydrolog zgłasza ostrzeżenie (aplikacja go nie pokazuje) poza powierzchnią 0,005–0,45 km² i spadkiem 0,03–0,10 m/m – zakresem danych Kirpicha.',
            sources: 'Kirpich 1940 (za Fang i in. 2005 i Roussel i in. 2005); Mota i Kobiyama 2015; USDA-NRCS 2010 (NEH 630-15)',
        },
        'hydro-tc-method:giandotti': {
            summary: 'Duże zlewnie włoskie (kalibracja: 12 zlewni, 170–70 000 km²); mniejsze zlewnie leżą poza zakresem kalibracji.',
            title: 'Giandotti (1934)',
            definition: 'Wzór skalibrowany na dużych zlewniach włoskich; uwzględnia powierzchnię, długość cieku głównego i wyniesienie średniej wysokości zlewni nad ujście.',
            formula: f`T_c = 60 · \frac{4 \sqrt{A} + 1,5 L_g}{0,8 \sqrt{H_{śr} - H_{min}}}`,
            variables: [A, L_G, H_MEAN, H_MIN],
            unit: 'min',
            meaning: '$T_c$ rośnie z powierzchnią i długością cieku, maleje ze wzrostem deniwelacji $H_{śr} - H_{min}$.\nW Hydrografie: $L_g$ – ciek główny z sieci z NMT, wysokością ujścia jest $H_{min}$. Bez cieku głównego albo średniej wysokości obliczenie kończy się komunikatem o brakujących danych – długość zlewni ani środek przedziału wysokości ich nie zastępują.',
            range: 'Kalibracja: 12 zlewni we Włoszech, 170–70 000 km², bez informacji o użytych wezbraniach. Hydrograf liczy hydrogram do 250 km², więc większość zlewni leży poniżej zakresu kalibracji. Hydrolog zgłasza ostrzeżenie (aplikacja go nie pokazuje) poza powierzchnią 170–70 000 km² – zakresem kalibracji.',
            sources: 'Giandotti 1934 (za Grimaldi i in. 2012)',
        },
        'hydro-tc-method:faa': {
            summary: 'Spływ powierzchniowy do wpustu (lotniska, tereny zurbanizowane); nomogram FAA: L do 0,24 km, spadek 0,5–2,5%.',
            title: 'FAA',
            definition: 'Wzór Federal Aviation Administration (FAA 1970, AC 150/5320-5B, rys. 7) do projektowania odwodnienia lotnisk: czas spływu po powierzchni od najdalszego punktu do wpustu („inlet time”).',
            formula: f`T_c = 22,213 · (1,1 - C) \frac{L_{sp}^{0,5}}{I_{sp}^{1/3}}`,
            variables: [
                ['C', 'współczynnik spływu z tab. I FAA (pole „C (spływ)”)', '–'],
                L_SP,
                ['I_{sp}', 'spadek odcinka spływu powierzchniowego', 'm/m'],
            ],
            unit: 'min',
            meaning: 'Liczy tylko czas spływu po powierzchni na długości $L_{sp}$ – przepływ korytem nie jest uwzględniany. Większy $C$ (powierzchnia szczelniejsza) i większy spadek skracają $T_c$.\nW Hydrografie: $L_{sp}$ i $I_{sp}$ – odcinek spływu powierzchniowego najdłuższej drogi spływu („Spływ powierzchniowy – długość” i „– spadek”), $C$ – z wymaganego pola „C (spływ)”; Hydrograf nie wylicza $C$.',
            range: 'Nomogram FAA obejmuje $L$ do 800 ft (0,24 km), spadki 0,5–2,5% i $C$ do 0,95; dłuższe odcinki liczy się wzorem. Hydrolog zgłasza ostrzeżenie (aplikacja go nie pokazuje) tylko przy $C$ powyżej 0,95 – największej wartości tab. I.',
            sources: 'FAA 1970; Fang i in. 2005',
        },
        'hydro-tc-method:kerby': {
            summary: 'Spływ po stoku w bardzo małych, płaskich zlewniach (dane: < 0,04 km², spadek < 1%, L do 0,366 km).',
            title: 'Kerby (1959)',
            definition: 'Wzór dla spływu po powierzchni stoku w bardzo małych, płaskich zlewniach.',
            formula: f`T_c = 36,37 · (L_{sp} N)^{0,467} I_{sp}^{-0,2335}`,
            variables: [
                L_SP,
                ['N', 'współczynnik oporu z tabeli Kerby’ego (pole „N (opór)”)', '–'],
                ['I_{sp}', 'spadek odcinka spływu powierzchniowego; poniżej 0,002 zwiększany o 0,0005', 'm/m'],
            ],
            unit: 'min',
            meaning: 'Opisuje tylko spływ po stoku: $T_c$ rośnie z długością i szorstkością $N$, maleje ze spadkiem; w małych zlewniach ten spływ może dominować w czasie koncentracji.\nW Hydrografie: $L_{sp}$ i $I_{sp}$ – odcinek spływu powierzchniowego najdłuższej drogi spływu („Spływ powierzchniowy – długość” i „– spadek”), $N$ – z wymaganego pola „N (opór)”.',
            range: 'Dane Kerby’ego: zlewnie poniżej 10 akrów (0,04 km²), spadki poniżej 1%, długość spływu do 1200 ft (0,366 km), $N$ do 0,8. Poprawkę spadku dla spadków poniżej 0,002 zaleca Cleveland i in. (2012). Hydrolog zgłasza ostrzeżenie (aplikacja go nie pokazuje) poza zakresem danych Kerby’ego: powierzchnią do 0,04 km², $L_{sp}$ do 0,366 km, spadkiem do 0,01 m/m i $N$ 0,02–0,80. Odcinek spływu powierzchniowego Hydrografu zależy od progu sieci cieków i przy dużym progu przekracza 0,366 km.',
            sources: 'Kerby 1959 (za Roussel i in. 2005); Fang i in. 2005; Cleveland i in. 2012 (TxDOT 0-6382-P1)',
        },
        'hydro-tc-method:kerby_kirpich': {
            summary: 'Spływ po stoku (Kerby) + koryto (Kirpich); weryfikacja: 92 zlewnie w Teksasie, 0,65–388 km².',
            title: 'Kerby-Kirpich',
            definition: 'Metoda złożona: czas spływu po stoku (Kerby) plus czas przepływu korytem (Kirpich). Koryto to najdłuższa droga spływu od punktu zlewni najdalszego hydraulicznie do ujścia bez odcinka spływu po stoku, a jego spadek liczy się na całej tej drodze.',
            formula: [
                'T_c = t_{sp} + t_k',
                f`t_{sp} = 36,37 · (L_{sp} N)^{0,467} I_{sp}^{-0,2335}`,
                f`t_k = 3,981 · (L_{max} - L_{sp})^{0,77} I_{dr}^{-0,385}`,
            ],
            variables: [
                L_SP,
                ['N', 'współczynnik oporu (pole „N (opór)”)', '–'],
                ['I_{sp}', 'spadek odcinka spływu powierzchniowego', 'm/m'],
                L_MAX,
                ['I_{dr}', 'spadek najdłuższej drogi spływu od punktu zlewni najdalszego hydraulicznie do ujścia', 'm/m'],
            ],
            unit: 'min',
            meaning: 'Rozdziela wolny spływ po stoku i szybszy przepływ korytem – kilometr spływu po stoku trwa zwykle znacznie dłużej niż kilometr w korycie. Dla 92 zlewni w Teksasie dawała $T_c$ zgodne z czasami do szczytu obserwowanych wezbrań.\nW Hydrografie drogę wody dzieli sieć cieków z NMT: odcinek do jej pierwszej komórki to spływ po stoku ($L_{sp}$, $I_{sp}$), reszta $L_{max} - L_{sp}$ to koryto ze spadkiem całej drogi $I_{dr}$ – jak w przykładzie TxDOT; $L_{max}$ musi być większa od $L_{sp}$. $N$ – z wymaganego pola „N (opór)”.',
            range: 'Zweryfikowana na 92 zlewniach w Teksasie: 0,65–388 km², ciek główny (od ujścia do działu wodnego) 1,6–80 km, jego spadek 0,002–0,02. Przy spadku poniżej 0,002 zaleca się dodać 0,0005 w obu częściach; Hydrolog robi to osobno dla każdego spadku. Hydrolog zgłasza ostrzeżenie (aplikacja go nie pokazuje) poza powierzchnią 0,65–388 km², $L_{sp}$ do 0,366 km, $N$ 0,02–0,80, $L_{max}$ 1,6–80 km i $I_{dr}$ 0,002–0,02.',
            sources: 'Roussel i in. 2005; TxDOT 2019; Cleveland i in. 2012 (TxDOT 0-6382-P1); USDA-SCS 1986 (TR-55)',
        },
    };
})();
