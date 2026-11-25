<!--
WZÓR REGULAMINU. NIE JEST PORADĄ PRAWNĄ.

Wzór regulaminu serwisu, który na własnej infrastrukturze prowadzi operator inny niż autor oprogramowania (Nogat, design/kit/nogat-terms-operator.md; DEV-15.7, ECO-079). Nie jest poradą ani opinią prawną. Przed użyciem regulamin sprawdza i dostosowuje do serwisu operatora prawnik.

Jak przygotować regulamin z tego wzoru:
1. Skopiuj plik do plików swojego wdrożenia, poza kopią kodu, i wskaż go w ustawieniach serwisu (w Obserwatorze: `terms` w sekcji [obserwator.instance] pliku nogat.toml).
2. Pola {{operator_address}} i {{operator_register}} wpisz sam. Pozostałe pola {{…}} serwis wypełnia z [nogat.operator] i [nogat.gui] pliku nogat.toml oraz z danych projektu, tak jak w regulaminie 1.0.
3. Bloki źródeł danych w § 5 zostaw bez zmian: serwis zostawia bloki dostawców, których dane udostępnia, i usuwa pozostałe.
4. Sprawdź, czy § 3, § 4 i § 8 opisują Twoje wdrożenie: odpłatność i cel serwisu wobec warunków dostawców danych (w tym celów, w jakich wolno wykorzystywać dane IMGW-PIB), dostęp, serwer pośredniczący i jego dzienniki, dostawcę ruchu i poczty, okresy przechowywania. Gdy serwis pokazuje dane z Twojej sieci pomiarowej, dopisz w § 5 ich źródło i zasady korzystania z nich.
5. Usuń ten komentarz. Serwis publikuje tylko regulamin, który zaczyna się od tytułu „# ”, i żaden, w którym zostało niewypełnione pole {{…}}.
-->
# Regulamin serwisu {{service_name}}

Wersja 1.0, obowiązuje od {{terms_effective}}

## 1. Postanowienia ogólne

1. Regulamin określa zasady korzystania z serwisu internetowego {{service_name}} pod adresem {{service_url}} (dalej: serwis), który prowadzi operator wskazany w § 2.
2. Dostawcy danych to instytucje i podmioty, których dane serwis pokazuje lub przetwarza (§ 5). Wyniki to wszystko, co serwis oblicza lub tworzy z danych dostawców albo z wartości, które wprowadzasz: wartości, tabele, wykresy, mapy i pliki.
3. Korzystając z serwisu, akceptujesz regulamin. Umowa o świadczenie usług drogą elektroniczną zostaje zawarta, gdy zaczynasz korzystać z serwisu, i wygasa, gdy przestajesz z niego korzystać, co możesz zrobić w każdej chwili.

## 2. Operator

1. Serwis prowadzi i świadczy w nim usługi drogą elektroniczną {{operator_name}}, {{operator_address}}, {{operator_register}} (dalej: operator), we własnym imieniu i na własny rachunek, na infrastrukturze, którą sam wybiera i za którą odpowiada.
2. Kontakt z operatorem: [{{operator_email}}](mailto:{{operator_email}}).

## 3. Charakter serwisu

1. Korzystanie z serwisu jest bezpłatne. Serwis udostępnia dane pomiarowe i wyniki obliczeń wyłącznie w celach informacyjnych.
2. Serwis nie jest serwisem żadnego z dostawców danych (§ 5). Pokazuje ich dane po przetworzeniu, a wyniki są obliczeniami serwisu: mają charakter wyłącznie informacyjny i nie są oficjalnymi produktami, prognozami, ostrzeżeniami ani komunikatami dostawców, ekspertyzą ani opracowaniem urzędowym.
3. Wyniki nie mogą być jedyną podstawą decyzji, w szczególności projektowych, inwestycyjnych, planistycznych lub dotyczących bezpieczeństwa ludzi i mienia, bez sprawdzenia przez osobę o odpowiednich kwalifikacjach i porównania z oficjalnymi źródłami.
4. W sytuacji zagrożenia powodziowego lub meteorologicznego kieruj się komunikatami IMGW-PIB (<https://hydro.imgw.pl>, <https://meteo.imgw.pl>) i służb, a nie serwisem.

## 4. Dostęp

1. Serwis jest dostępny publicznie, bez rejestracji i logowania.
2. Z serwisu korzystasz przez przeglądarkę albo, gdy serwis udostępnia interfejs programistyczny (API), przez program, który z niego korzysta, np. wtyczkę QGIS Goniec ekosystemu Nogat. Regulamin dotyczy obu sposobów.
3. Do korzystania z serwisu potrzebne są urządzenie z dostępem do internetu i aktualna przeglądarka internetowa z włączoną obsługą JavaScriptu albo program korzystający z API serwisu.
4. Operator może w każdej chwili ograniczyć, zawiesić lub zakończyć udostępnianie serwisu albo jego części, w szczególności przy przeciążeniu, pracach technicznych, naruszeniu regulaminu lub zmianie warunków dostawców danych.

## 5. Źródła danych i ich warunki

1. Serwis dołącza do widoków, plików i wyników informacje, których wymagają dostawcy danych. Podaje je niżej, przy każdym dostawcy, z odnośnikiem do jego regulaminu lub licencji.
2. Korzystanie z danych i wyników pobranych z serwisu, w tym z plików, wykresów i zrzutów ekranu, podlega regulaminom i licencjom dostawców, do których odsyłają te odnośniki.
3. Dostawcy danych nie są stronami regulaminu i nie odpowiadają za serwis ani za wyniki.
4. Za przestrzeganie w serwisie warunków dostawców danych, w tym za wymagane przez nich oznaczenia i dopuszczalne cele wykorzystania danych, odpowiada operator.

<!-- block: imgw -->
### IMGW-PIB: dane publiczne

> Źródłem pochodzenia danych jest Instytut Meteorologii i Gospodarki Wodnej – Państwowy Instytut Badawczy
> Dane Instytutu Meteorologii i Gospodarki Wodnej – Państwowego Instytutu Badawczego zostały przetworzone

Regulamin danych IMGW-PIB: <https://danepubliczne.imgw.pl/regulations>
<!-- /block -->

<!-- block: imgw-hydro -->
### IMGW-PIB: serwis hydrologiczny

> Źródłem pochodzenia danych jest Instytut Meteorologii i Gospodarki Wodnej – Państwowy Instytut Badawczy
> Dane Instytutu Meteorologii i Gospodarki Wodnej – Państwowego Instytutu Badawczego zostały przetworzone

Regulamin serwisu hydrologicznego IMGW-PIB: <https://hydro.imgw.pl/#/regulamin>
<!-- /block -->

<!-- block: pmaxtp -->
### IMGW-PIB: opady maksymalne PMAXTP

> Źródłem pochodzenia danych jest Instytut Meteorologii i Gospodarki Wodnej – Państwowy Instytut Badawczy, dane pochodzą ze strony https://klimat.imgw.pl/opady-maksymalne
> Dane Instytutu Meteorologii i Gospodarki Wodnej – Państwowego Instytutu Badawczego pochodzące ze strony https://klimat.imgw.pl/opady-maksymalne zostały przetworzone
> „Modele probabilistyczne opadów maksymalnych o określonym czasie trwania i prawdopodobieństwie przewyższenia – Projekt PMAXTP”, red. Bogdan Ozga-Zieliński, Instytut Meteorologii i Gospodarki Wodnej – Państwowy Instytut Badawczy, Warszawa 2022

Regulamin danych PMAXTP: <https://klimat.imgw.pl/opady-maksymalne>
<!-- /block -->

<!-- block: chmu -->
### ČHMÚ

> Źródło danych: Český hydrometeorologický ústav (ČHMÚ), https://opendata.chmi.cz, licencja CC BY 4.0 (https://creativecommons.org/licenses/by/4.0/)
> Dane ČHMÚ zostały przetworzone
<!-- /block -->

<!-- block: camels-pl -->
### CAMELS-PL

> Źródło danych: CAMELS-PL
> Dane CAMELS-PL zostały przetworzone

Licencja CC BY 4.0: <https://creativecommons.org/licenses/by/4.0/>
<!-- /block -->

<!-- block: e-obs -->
### E-OBS

> We acknowledge the E-OBS dataset and the data providers in the ECA&D project (https://www.ecad.eu). Cornes, R., G. van der Schrier, E.J.M. van den Besselaar, and P.D. Jones. 2018: An Ensemble Version of the E-OBS Temperature and Precipitation Datasets, J. Geophys. Res. Atmos., 123. doi:10.1029/2017JD028200

Regulamin danych E-OBS: <https://www.ecad.eu/documents/ECAD_datapolicy.pdf>
<!-- /block -->

<!-- block: pig -->
### PIG-PIB: monitoring wód podziemnych

> Źródło danych: Państwowy Instytut Geologiczny – Państwowy Instytut Badawczy (PIG-PIB), Monitoring Wód Podziemnych
> Dane PIG-PIB zostały przetworzone

Regulamin danych PIG-PIB: <https://www.pgi.gov.pl/rejestry-i-bazy-danych-geologicznych/zasady-korzystania-z-isp.html>

Licencja CC BY 4.0: <https://creativecommons.org/licenses/by/4.0/>
<!-- /block -->

<!-- block: gugik -->
### GUGiK

> Źródło: Główny Urząd Geodezji i Kartografii – GUGiK

Warunki ponownego wykorzystywania danych GUGiK: <https://www.gov.pl/web/gugik/ponowne-wykorzystanie-informacji-sektora-publicznego>
<!-- /block -->

<!-- block: cuzk -->
### ČÚZK

> Źródło: ČÚZK

Licencja CC BY 4.0: <https://creativecommons.org/licenses/by/4.0/>
<!-- /block -->

<!-- block: copernicus -->
### Copernicus

> © Unia Europejska, Copernicus Land Monitoring Service, Europejska Agencja Środowiska (EEA)

Polityka danych Copernicus: <https://land.copernicus.eu/en/data-policy>
<!-- /block -->

<!-- block: isric -->
### ISRIC SoilGrids

> Źródło: ISRIC – World Soil Information

Licencja CC BY 4.0: <https://creativecommons.org/licenses/by/4.0/>
<!-- /block -->

<!-- block: wody-polskie -->
### Wody Polskie

> Źródło: Państwowe Gospodarstwo Wodne Wody Polskie

Licencja CC BY 4.0: <https://creativecommons.org/licenses/by/4.0/>
<!-- /block -->

<!-- block: osm -->
### OpenStreetMap (kafelki OpenFreeMap, podkład OSM serwisu geoportal.gov.pl)

> © autorzy OpenStreetMap

Licencja ODbL: <https://www.openstreetmap.org/copyright>
<!-- /block -->

## 6. Twoje obowiązki

1. Korzystasz z serwisu zgodnie z prawem i regulaminem.
2. Nie pobierasz danych automatycznie (scraping, masowe zapytania) w sposób, który obciąża serwis lub utrudnia korzystanie z niego innym, nie obchodzisz jego zabezpieczeń, w tym limitu żądań, i nie próbujesz dostać się do jego części administracyjnych. Programy korzystają z serwisu przez jego API, gdy je udostępnia, w granicach limitu żądań. Do pobierania wielu danych służą narzędzia ekosystemu Nogat i serwisy dostawców.
3. W zgłoszeniach nie przekazujesz treści bezprawnych ani danych osobowych (§ 8).

## 7. Odpowiedzialność

1. Serwis jest udostępniany w stanie, w jakim jest, i korzystasz z niego na własne ryzyko. Operator nie gwarantuje dostępności serwisu ani poprawności, kompletności i aktualności danych dostawców i wyników: wyniki oblicza otwarte oprogramowanie (§ 9), które może zawierać błędy, a dane operacyjne mogą być niesprawdzone i niepełne.
2. Operator nie ponosi odpowiedzialności za szkody wynikłe z korzystania z serwisu, w tym z decyzji podjętych na podstawie jego wyników, z wyjątkiem szkód wyrządzonych umyślnie.
3. Operator nie odpowiada za treść stron dostawców i innych stron, do których serwis odsyła.
4. Autor oprogramowania nie odpowiada za serwis, jego dostępność, dane dostawców ani wyniki (§ 9).

## 8. Dane osobowe

1. Administratorem Twoich danych osobowych przetwarzanych w związku z serwisem jest operator, {{operator_name}}, {{operator_address}}, kontakt: [{{operator_email}}](mailto:{{operator_email}}). Autor oprogramowania nie jest administratorem tych danych ani podmiotem, który przetwarza je w imieniu operatora.
2. Serwis nie wymaga podania żadnych danych i nie zapisuje adresów IP. Twój adres IP, bez którego nie da się dostarczyć strony, serwer przetwarza tylko w pamięci operacyjnej: liczy żądania z tego adresu, aby ograniczyć ich liczbę w krótkim czasie, oraz tworzy z adresu IP, oznaczenia przeglądarki (User-Agent) i losowej wartości skrót, którym liczy odwiedzających danego dnia. Losowa wartość i skróty są tylko w pamięci i znikają najpóźniej o północy UTC; na dysk trafiają wyłącznie łączne liczby z każdego dnia: odwiedzający, odsłony, otwarte stacje, wykonane analizy i pobrania. Podstawą jest prawnie uzasadniony interes operatora: bezpieczeństwo serwisu, ochrona przed nadmierną liczbą żądań i statystyka użycia (art. 6 ust. 1 lit. f RODO).
3. Dzienniki serwera nie zawierają adresu IP. Dziennik żądań i dziennik błędów są usuwane po 14 dniach, a komunikaty o uruchomieniu i zatrzymaniu serwera oraz o jego błędach nie zawierają danych żądań. Dziennik żądań zapisuje czas, metodę i adres żądanej strony z parametrami, kod i rozmiar odpowiedzi, czas obsługi, losowy identyfikator żądania i rodzaj programu, który je wysłał: przeglądarka, robot albo inny program.
4. Ruch do serwisu przechodzi przez {{processor}}, który przetwarza go, w tym Twój adres IP, w imieniu operatora jako podmiot przetwarzający na podstawie umowy powierzenia zawartej w jego warunkach świadczenia usług, i może prowadzić własne dzienniki bezpieczeństwa zgodnie ze swoją polityką prywatności. {{processor_transfer}}
5. Podkład mapowy i warstwy map innych dostawców (§ 5) Twoja przeglądarka pobiera bezpośrednio z ich serwerów, które otrzymują przy tym Twój adres IP.
6. Formularz „Zgłoś uwagę” przesyła tylko treść zgłoszenia i kontekst dodany przez serwis: widok, stację, parametry widoku i wersję aplikacji; nie ma pól kontaktowych i nie zapisuje adresu IP. Nie wpisuj w nim danych osobowych; jeśli chcesz odpowiedzi, napisz e-mail. Zgłoszenia i e-maile operator przetwarza, aby je załatwić (art. 6 ust. 1 lit. f RODO), i usuwa po załatwieniu sprawy. E-maile do operatora są przechowywane w jego skrzynce w usłudze {{mail_provider}}. {{mail_transfer}}
7. Ustawienia (motyw, układ widoków, układ współrzędnych, podkład mapy) i wprowadzone dane serwis zapamiętuje w pamięci Twojej przeglądarki (localStorage), bo o to prosisz, korzystając z tych funkcji; usuniesz je w ustawieniach przeglądarki. Wartości i pliki, które przekazujesz do obliczeń, serwer wykorzystuje tylko do ich wykonania. Serwis nie ustawia własnych plików cookie i nie korzysta z zewnętrznych narzędzi analitycznych ani reklamowych. {{processor_cookie}}
8. Masz prawo dostępu do swoich danych, ich sprostowania, usunięcia i ograniczenia przetwarzania oraz prawo sprzeciwu (art. 15–18 i 21 RODO); w praktyce dotyczą one e-maili i zgłoszeń, bo adresu IP, skrótu ani dzienników operator nie potrafi przypisać do osoby (art. 11 RODO). Żądanie wyślij na adres operatora; odpowiada w ciągu miesiąca (art. 12 ust. 3 RODO). Przysługuje Ci prawo wniesienia skargi do Prezesa Urzędu Ochrony Danych Osobowych (<https://uodo.gov.pl>).

## 9. Oprogramowanie serwisu

1. Serwis działa na otwartym oprogramowaniu, które jego autor udostępnia na licencji {{software_licence}}; kod źródłowy: <{{source_url}}>. Licencja oprogramowania nie obejmuje danych dostawców ani wyników z nich utworzonych (§ 5).
2. Zgodnie z licencją oprogramowanie jest udostępniane w stanie, w jakim jest, bez jakiejkolwiek gwarancji, wyraźnej ani dorozumianej, a jego autor nie odpowiada za szkody związane z oprogramowaniem lub z korzystaniem z niego, w tym za dostępność serwisu, dane dostawców i wyniki.
3. Autor oprogramowania nie jest operatorem ani usługodawcą, nie jest stroną regulaminu i nie prowadzi serwisu. Jeśli wdrożył serwis na zlecenie operatora, jego udział zakończył się z przekazaniem wdrożenia operatorowi. Prowadzenie serwisu, jego ustawienia, aktualizacje, kopie zapasowe i bezpieczeństwo należą do operatora.

## 10. Kontakt, zgłoszenia i reklamacje

1. Uwagi, pytania i błędy zgłaszaj na adres [{{operator_email}}](mailto:{{operator_email}}) albo przez formularz „Zgłoś uwagę” (na zgłoszenie z formularza operator nie może odpowiedzieć). Operator odpowiada w miarę możliwości, a na żądania dotyczące danych osobowych w ciągu miesiąca (§ 8).
2. Reklamację dotyczącą działania serwisu wyślij e-mailem na adres operatora i opisz w niej, czego dotyczy. Operator rozpatruje ją w ciągu 14 dni od jej otrzymania i odpowiada na adres, z którego ją wysłano.
3. Zgłoszenia i reklamacje dotyczące serwisu przyjmuje i rozpatruje wyłącznie operator, nie autor oprogramowania.

## 11. Zmiany regulaminu

1. Operator może zmienić regulamin, w szczególności przy zmianie serwisu, przepisów lub warunków dostawców danych. Nowa wersja obowiązuje od opublikowania pod tym samym adresem, bez wcześniejszego powiadomienia; jej numer i datę podaje początek regulaminu, a zmiany – „Historia zmian” na końcu.
2. Zmiana nie dotyczy korzystania z serwisu przed jej wejściem w życie.

## 12. Postanowienia końcowe

1. Do regulaminu stosuje się prawo polskie. Regulamin jest sporządzony w języku polskim; ewentualne tłumaczenia mają charakter pomocniczy.
2. Regulamin nie ogranicza praw, które przysługują Ci na podstawie bezwzględnie obowiązujących przepisów.

## Historia zmian

- **1.0**: pierwsza wersja.

Poprzednie wersje regulaminu operator udostępnia na żądanie wysłane na adres [{{operator_email}}](mailto:{{operator_email}}).
