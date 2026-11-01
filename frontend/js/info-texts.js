/**
 * Hydrograf explanation texts for the (i) markers (js/info.js).
 *
 * Keys are the API/morphometry field names (result rows) and the form
 * control ids (form fields). Entries with { note, text } describe the
 * applicability of one option of a select: `note` is the compact line
 * under the select, `text` the full description in its (i) tooltip.
 * Grounded in the Hydrolog / Hydrograf sources (tooltips-source.md).
 */
(function () {
    'use strict';

    window.Hydrograf = window.Hydrograf || {};

    window.Hydrograf.infoTexts = {
        // ── Parametry podstawowe ───────────────────────────────────────
        area_km2: 'Powierzchnia A poligonu zlewni wydzielonej z NMT, w km². ' +
            'Wchodzi do wskaźników kształtu i do modeli hydrogramu; hydrogram liczony jest dla zlewni do 250 km².',
        perimeter_km: 'Obwód P – długość granicy zlewni (działu wodnego) wydzielonej z NMT, w km. ' +
            'Służy do wskaźników zwartości C_z i kolistości C_k.',
        length_km: 'Długość zlewni L – największy wymiar zlewni od ujścia do działu wodnego, w km. ' +
            'Służy do średniej szerokości i wskaźników C_w, C_f, C_l.',
        mean_width_km: 'Średnia szerokość B = A / L, w km. ' +
            'Im mniejsza względem długości zlewni, tym zlewnia bardziej wydłużona.',
        elevation_min_m: 'Najniższa wysokość terenu w granicach zlewni odczytana z NMT, w m n.p.m. ' +
            'Metoda Giandottiego liczy deniwelację ΔH od tej wysokości.',
        elevation_max_m: 'Najwyższa wysokość terenu w granicach zlewni odczytana z NMT, w m n.p.m. ' +
            'Różnica H_max − H_min to deniwelacja zlewni.',
        elevation_mean_m: 'Średnia wysokość terenu zlewni z NMT, w m n.p.m. ' +
            'Metoda Giandottiego używa ΔH = wysokość średnia − wysokość min.',
        mean_slope_m_per_m: 'Średni spadek terenu zlewni – średnia ze spadków terenu z NMT ważona powierzchnią, pokazana w %. ' +
            'Hydrograf używa go jako spadku w metodach Tc NRCS, FAA, Kerby i w części spływu powierzchniowego Kerby-Kirpich.',
        channel_length_km: 'Długość cieku głównego od ujścia do działu wodnego, wyznaczona po sieci spływu z NMT, w km. ' +
            'Używają jej metoda Giandottiego oraz modele Snydera i Nasha (Lutz).',
        real_channel_length_km: 'Część cieku głównego pokrywająca się z ciekami z bazy BDOT, w km. ' +
            'Metoda Kerby-Kirpich przyjmuje ją jako długość koryta; jej udział w całym cieku to „Pokrycie BDOT”.',
        channel_slope_m_per_m: 'Spadek cieku głównego = różnica wysokości wzdłuż cieku / długość cieku, pokazany w %. ' +
            'Wchodzi do metod Kirpicha i Kerby-Kirpich (koryto) oraz do estymacji Nasha metodą Lutza.',
        hydraulic_length_km: 'Najdłuższa droga spływu wody od działu wodnego do ujścia, po kierunkach spływu z NMT, w km. ' +
            'Hydrograf używa jej jako długości w metodach Tc NRCS i Kirpicha.',
        divide_flow_path_km: 'Droga spływu od najdalszego punktu granicy zlewni (działu wodnego) do ujścia, z rastra odległości spływu, w km.',
        cn: 'Parametr CN metody SCS (1–100): im wyższy, tym mniejsza retencja zlewni i większy odpływ. ' +
            'Hydrograf liczy go z pokrycia terenu; gdy to niemożliwe, przyjmuje 75.',
        latitude: 'Szerokość geograficzna ujścia zlewni (WGS84), w °N.',
        longitude: 'Długość geograficzna ujścia zlewni (WGS84), w °E.',
        elevation_m: 'Wysokość terenu w punkcie ujścia odczytana z NMT, w m n.p.m.',

        // ── Wskaźniki kształtu (A – powierzchnia, P – obwód, L – długość) ──
        compactness_coefficient: 'Wskaźnik zwartości Graveliusa C_z = P / (2√(πA)). ' +
            'Dla koła C_z = 1, dla kwadratu ok. 1,12; powyżej 1,5 zlewnia jest wydłużona.',
        circularity_ratio: 'Wskaźnik kolistości Millera C_k = 4πA / P². ' +
            'Dla koła C_k = 1, dla kwadratu ok. 0,785; mniejsze wartości to zlewnia mniej zwarta.',
        elongation_ratio: 'Wskaźnik wydłużenia Schumma C_w = (2/L)·√(A/π). ' +
            'Dla koła C_w = 1; wartości 0,6–0,8 oznaczają zlewnię wydłużoną.',
        form_factor: 'Wskaźnik formy Hortona C_f = A / L². ' +
            'Poniżej 0,5 zlewnia wydłużona, ok. 0,75 zwarta, powyżej 0,75 kolista.',
        lemniscate_ratio: 'Wskaźnik lemniskaty Chorleya C_l = L² / (4A) porównuje kształt zlewni z lemniskatą. ' +
            'Większa wartość oznacza zlewnię bardziej wydłużoną.',

        // ── Hietogram: formularz ───────────────────────────────────────
        'hydro-duration': 'Czas trwania opadu projektowego. ' +
            'Wysokość opadu dla wybranego czasu i prawdopodobieństwa pochodzi z danych PMAXTP, interpolowanych (IDW) z 4 najbliższych punktów siatki do klikniętego punktu.',
        'hydro-probability': 'Prawdopodobieństwo przewyższenia opadu p. ' +
            'Im mniejsze p, tym rzadszy i wyższy opad (okres powtarzalności T = 1/p).',
        'hydro-hietogram-type': 'Rozkład wysokości opadu w czasie trwania. ' +
            'Beta – kształt sterowany parametrami α i β; DVWK (Euler II) – szczyt w 1/3 czasu trwania; Blokowy – stałe natężenie przez cały czas.',
        'hydro-alpha': 'Parametr α rozkładu Beta (0,1–20, domyślnie 2). ' +
            'Przy α = β rozkład jest symetryczny; α mniejsze od β przesuwa szczyt opadu na początek.',
        'hydro-beta': 'Parametr β rozkładu Beta (0,1–20, domyślnie 5). ' +
            'Przy α = β rozkład jest symetryczny; β większe od α przesuwa szczyt opadu na początek.',

        // ── Hietogram: wyniki ──────────────────────────────────────────
        total_precip_mm: 'Całkowita wysokość opadu projektowego: suma opadu we wszystkich krokach hietogramu, w mm.',
        total_effective_mm: 'Opad efektywny – część opadu, która odpływa. ' +
            'Metoda SCS-CN krok po kroku: Pe = (P − Ia)² / (P − Ia + S), w mm.',
        runoff_coefficient: 'Współczynnik odpływu C = Pe / P (opad efektywny / opad całkowity). ' +
            'Mówi, jaka część opadu odpływa; 0 – nic, 1 – całość.',
        cn_used: 'Wartość CN użyta w obliczeniu strat (1–100) – z pokrycia terenu zlewni lub domyślna 75.',
        retention_mm: 'Maksymalna retencja zlewni S = 25400 / CN − 254, w mm. ' +
            'Im większa, tym więcej opadu zostaje w zlewni.',
        initial_abstraction_mm: 'Straty początkowe Ia = 0,2·S, w mm (standard SCS). ' +
            'Dopóki opad nie przekroczy Ia, nie ma odpływu.',

        // ── Hydrogram: formularz ───────────────────────────────────────
        'hydro-uh-model': 'Model hydrogramu jednostkowego, który zamienia opad efektywny w odpływ (splot z hietogramem). ' +
            'SCS – bezwymiarowy hydrogram NRCS; Nash – kaskada zbiorników liniowych; Snyder – hydrogram syntetyczny z morfometrii.',
        'hydro-tc-method': 'Metoda obliczania czasu koncentracji Tc – czasu dobiegu wody z najdalszego punktu zlewni do ujścia, w min. ' +
            'Model SCS przyjmuje opóźnienie t_lag = 0,6·Tc.',
        'hydro-tc-runoff-coeff': 'Współczynnik spływu C metody FAA (0–1). ' +
            'Puste pole: Hydrograf liczy C z CN jako C = 1 − S / (S + 25,4). Typowy zakres metody to 0,10–0,95.',
        'hydro-tc-retardance': 'Współczynnik oporu N Kerby’ego (domyślnie 0,4). ' +
            'Typowo: 0,02 gładkie nawierzchnie, 0,10 goła ubita gleba, 0,20 uprawy i słaba trawa, 0,40 pastwisko, 0,60 las liściasty, 0,80 gęsta trawa lub las iglasty.',
        'hydro-tc-overland-length': 'Długość spływu powierzchniowego (warstwowego) od działu wodnego do początku koryta, w km. ' +
            'Wymagana dla FAA (typowo 0,015–3 km) i Kerby (0,01–0,366 km); w Kerby-Kirpich puste pole = najdłuższa droga spływu minus długość koryta.',
        'hydro-nash-estimation': 'Sposób wyznaczenia parametrów kaskady Nasha: liczby zbiorników N i stałej K. ' +
            'Lutz – z cech fizjograficznych; regresja urbanizacyjna – z powierzchni, opadu efektywnego i urbanizacji; z Tc – przestarzała.',
        'hydro-nash-n': 'Liczba zbiorników N kaskady Nasha w estymacji „z Tc” (domyślnie 3). ' +
            'Stała zbiornika K = 0,6·Tc / N.',
        'hydro-snyder-ct': 'Współczynnik czasu Ct: opóźnienie tL = Ct·(L·Lc)^0,3 [h], L i Lc w km. ' +
            'Typowo 1,35–1,65: mniejsze dla zlewni stromych, górskich, większe dla płaskich, podmokłych.',
        'hydro-snyder-cp': 'Współczynnik szczytu Cp: qp = 0,275·Cp·A / tL [m³/s na mm]. ' +
            'Typowo 0,4–0,8: mniejsze przy dużej retencji (zlewnie wiejskie), większe przy małej (miejskie).',

        // ── Hydrogram: wyniki ──────────────────────────────────────────
        peak_discharge_m3s: 'Przepływ maksymalny Qmax – szczyt hydrogramu odpływu, w m³/s.',
        time_to_peak_min: 'Czas do szczytu tp – od początku opadu do wystąpienia Qmax, w min.',
        total_volume_m3: 'Objętość odpływu V – pole pod hydrogramem, w m³.',
        tc_method: 'Metoda, którą policzono czas koncentracji Tc.',
        tc_min: 'Czas koncentracji Tc wybraną metodą, w min – czas dobiegu wody z najdalszego punktu zlewni do ujścia.',
        uh_model: 'Użyty model hydrogramu jednostkowego; dla Nasha w nawiasie sposób estymacji parametrów.',
        nash_n: 'Liczba zbiorników liniowych N kaskady Nasha. ' +
            'Czas do szczytu hydrogramu chwilowego to (N − 1)·K.',
        nash_k_min: 'Stała retencji K jednego zbiornika kaskady Nasha, w min. ' +
            'Opóźnienie zlewni t_lag = N·K.',
        nash_urban_fraction: 'Wskaźnik urbanizacji U – udział terenów zabudowanych w powierzchni zlewni (tu w %), użyty w regresji urbanizacyjnej Nasha.',
        nash_effective_precip_mm: 'Opad efektywny H, który wchodzi do regresji urbanizacyjnej Nasha, w mm.',
        nash_duration_h: 'Czas trwania opadu efektywnego D z hietogramu po stratach SCS, użyty w regresji urbanizacyjnej Nasha.',

        // ── Zakres stosowalności: modele UH ────────────────────────────
        'hydro-uh-model:scs': {
            note: 'Model ogólnego zastosowania; brak formalnych granic, opracowany dla warunków USA.',
            text: 'Bezwymiarowy hydrogram NRCS (TR-55, 1986): t_lag = 0,6·Tc, tp = D/2 + t_lag, qp = 0,208·A / tp [m³/s na mm]. ' +
                'Kod nie ogranicza powierzchni ani Tc; tablica empirycznie sprawdzona na wielu zlewniach USA. ' +
                'Na bardzo płaskim terenie może zaniżać szczyt.',
        },
        'hydro-uh-model:nash': {
            note: 'Kaskada zbiorników; zakres zależy od wybranej estymacji N i K.',
            text: 'Hydrogram chwilowy Nasha: zlewnia jako N jednakowych zbiorników liniowych o stałej K; opóźnienie t_lag = N·K, czas do szczytu (N − 1)·K. ' +
                'Zakres stosowalności wynika ze sposobu estymacji (Lutz, regresja urbanizacyjna, z Tc).',
        },
        'hydro-uh-model:snyder': {
            note: 'Ct 1,35–1,65, Cp 0,4–0,8; brak formalnych granic, kalibracja na zlewniach USA.',
            text: 'Syntetyczny hydrogram Snydera (1938): tL = Ct·(L·Lc)^0,3 [h], qp = 0,275·Cp·A / tL. ' +
                'Kalibrowany na małych i średnich zlewniach USA; kod nie ostrzega o zakresach, a dla regionów odległych od USA zalecane są lokalne Ct i Cp. ' +
                'Wymaga długości cieku i odległości do środka ciężkości zlewni.',
        },

        // ── Zakres stosowalności: estymacja Nasha ──────────────────────
        'hydro-nash-estimation:from_lutz': {
            note: 'Zalecana dla zlewni niekontrolowanych; kalibracja: zlewnie górskie i podgórskie Niemiec i Polski, 20–500 km².',
            text: 'Metoda Lutza (1984; KZGW 2017): tp z długości cieku L, odległości do środka ciężkości Lc, spadku cieku, szorstkości koryta, urbanizacji i lesistości; N i K wynikają z tp. ' +
                'Kalibrowana głównie na zlewniach górskich i podgórskich Niemiec i Polski (20–500 km²), zlewnie naturalne. ' +
                'Wymaga długości i spadku cieku oraz Lc ≤ L.',
        },
        'hydro-nash-estimation:from_urban_regression': {
            note: 'Zlewnie zurbanizowane; kalibracja: ok. 12,9–51,8 km², urbanizacja do 0,5 (Indianapolis).',
            text: 'Regresja Rao, Delleura i Sarmy: tL = 1,28·A^0,46·(1+U)^−1,66·H^−0,27·D^0,37, k = 0,56·A^0,39·(1+U)^−0,62·H^−0,11·D^0,22 [min], N = tL / k. ' +
                'Wyprowadzona z ok. 200 opadów na zlewniach koło Indianapolis o powierzchni ok. 12,9–51,8 km² i urbanizacji 0–0,5. ' +
                'Kod przyjmuje U z zakresu 0–1, ale poza kalibracją nie ostrzega.',
        },
        'hydro-nash-estimation:from_tc': {
            note: 'Przestarzała: relacja SCS t_lag = 0,6·Tc nie ma uzasadnienia dla modelu Nasha.',
            text: 'K = 0,6·Tc / N przy zadanym N. ' +
                'Relacja t_lag = 0,6·Tc pochodzi z hydrogramu SCS, a w kaskadzie Nasha opóźnienie N·K wynika z jej budowy – metoda jest oznaczona jako przestarzała. ' +
                'Lepiej użyć estymacji Lutza lub regresji urbanizacyjnej.',
        },

        // ── Zakres stosowalności: metody Tc ────────────────────────────
        'hydro-tc-method:nrcs': {
            note: 'L 0,03–30 km, spadek 0,1–15%, CN 50–95 (TR-55).',
            text: 'NRCS (SCS Lag, TR-55 1986), uwzględnia CN: tc = 0,01416·L[m]^0,8·(S + 25,4)^0,7·s[%]^−0,5 [min], S = 25400/CN − 254. ' +
                'Poza zakresem długości 0,03–30 km, spadku 0,001–0,15 m/m lub CN 50–95 Hydrolog ostrzega.',
        },
        'hydro-tc-method:kirpich': {
            note: 'Małe zlewnie rolnicze; L do 80 km, spadek 0,2–15%.',
            text: 'Kirpich (1940): tc = 3,981·L[km]^0,77·S[m/m]^−0,385 [min]. ' +
                'Skalibrowany na 7 małych zlewniach rolniczych w Tennessee (0,004–0,45 km²). ' +
                'Hydrolog ostrzega przy długości powyżej 80 km lub spadku poza 0,002–0,15 m/m.',
        },
        'hydro-tc-method:giandotti': {
            note: 'Duże zlewnie górskie, A od 100 km²; L 1–300 km, ΔH 20–3000 m.',
            text: 'Giandotti (1934): tc = (4√A + 1,5·L) / (0,8·√ΔH) [h], ΔH – różnica wysokości średniej i minimalnej zlewni. ' +
                'Opracowany dla dużych włoskich zlewni górskich (typowo 100–10 000 km²). ' +
                'Hydrolog ostrzega przy A < 100 km², L poza 1–300 km lub ΔH poza 20–3000 m.',
        },
        'hydro-tc-method:faa': {
            note: 'Spływ powierzchniowy; L 0,015–3 km, spadek 0,5–10%, C 0,10–0,95.',
            text: 'FAA (drenaż lotnisk), dla spływu powierzchniowego po względnie płaskich powierzchniach: tc = 22,213·(1,1 − C)·L[km]^0,5 / S[m/m]^(1/3) [min]. ' +
                'Hydrolog ostrzega przy długości poza 0,015–3 km, spadku poza 0,005–0,10 m/m lub C poza 0,10–0,95.',
        },
        'hydro-tc-method:kerby': {
            note: 'Spływ warstwowy na płaskim terenie; L 0,01–0,366 km, spadek 0,1–1%, N 0,02–0,80.',
            text: 'Kerby (1959), płytki spływ warstwowy w małych, płaskich zlewniach: tc = 36,37·(L[km]·N)^0,467·S^−0,2335 [min]; przy S < 0,002 spadek zwiększany o 0,0005. ' +
                'Hydrolog ostrzega przy długości poza 0,01–0,366 km, spadku poza 0,001–0,01 m/m lub N poza 0,02–0,80.',
        },
        'hydro-tc-method:kerby_kirpich': {
            note: 'Spływ pow. (Kerby) + koryto (Kirpich); zweryfikowana na 92 zlewniach w Teksasie, 0,65–388 km².',
            text: 'Metoda złożona: tc = tc spływu powierzchniowego (Kerby) + tc w korycie (Kirpich). ' +
                'Zweryfikowana na 92 zlewniach w Teksasie (0,65–388 km²). ' +
                'Ostrzeżenia osobno dla części: spływ L 0,01–0,366 km, spadek 0,001–0,01 m/m, N 0,02–0,80; koryto L do 80 km, spadek 0,002–0,15 m/m.',
        },
    };
})();
