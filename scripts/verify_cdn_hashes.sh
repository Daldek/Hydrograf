#!/usr/bin/env bash
# verify_cdn_hashes.sh — weryfikuje hashe SRI zasobów CDN w index.html
#
# Użycie:
#   ./scripts/verify_cdn_hashes.sh
#   ./scripts/verify_cdn_hashes.sh --fix   # napraw nieprawidłowe hashe
#
# Wymaga: curl, openssl, grep, sed
set -euo pipefail

HTML="frontend/index.html"
FIX_MODE=false
ERRORS=0
CHECKED=0

if [[ "${1:-}" == "--fix" ]]; then
    FIX_MODE=true
fi

if [[ ! -f "$HTML" ]]; then
    echo "BŁĄD: nie znaleziono $HTML (uruchom z katalogu głównego projektu)" >&2
    exit 1
fi

# Wyciągnij pary (URL, algorytm-hash) z atrybutów src/href + integrity
# Obsługuje wieloliniowe tagi <script> i <link>
extract_entries() {
    # Złącz linie kontynuacji, wyciągnij URL + integrity
    perl -0777 -ne '
        while (/<(?:script|link)\b[^>]*?\b(?:src|href)="(https?:\/\/[^"]+)"[^>]*?\bintegrity="(sha\d+-[^"]+)"/gs) {
            print "$1 $2\n";
        }
    ' "$HTML"
}

verify_entry() {
    local url="$1"
    local declared="$2"
    local algo hash_expected

    # Rozbij "sha384-abc123..." na algorytm i hash
    algo="${declared%%-*}"    # sha256 | sha384 | sha512
    hash_expected="${declared#*-}"

    # Mapuj na parametr openssl
    local ossl_algo
    case "$algo" in
        sha256) ossl_algo="sha256" ;;
        sha384) ossl_algo="sha384" ;;
        sha512) ossl_algo="sha512" ;;
        *) echo "  NIEZNANY ALGORYTM: $algo"; return 1 ;;
    esac

    # Pobierz i oblicz hash
    local hash_actual
    hash_actual=$(curl -sf --max-time 15 "$url" | openssl dgst -"$ossl_algo" -binary | openssl base64 -A)

    if [[ -z "$hash_actual" ]]; then
        echo "  BŁĄD POBIERANIA: $url"
        return 1
    fi

    CHECKED=$((CHECKED + 1))

    if [[ "$hash_actual" == "$hash_expected" ]]; then
        echo "  OK  $url"
        return 0
    else
        echo "  FAIL $url"
        echo "       oczekiwany: ${algo}-${hash_expected}"
        echo "       rzeczywisty: ${algo}-${hash_actual}"

        if $FIX_MODE; then
            sed -i "s|${algo}-${hash_expected}|${algo}-${hash_actual}|g" "$HTML"
            echo "       NAPRAWIONO w $HTML"
        fi

        return 1
    fi
}

echo "Weryfikacja hashów SRI w $HTML..."
echo ""

while IFS=' ' read -r url integrity; do
    if ! verify_entry "$url" "$integrity"; then
        ERRORS=$((ERRORS + 1))
    fi
done < <(extract_entries)

echo ""
echo "Sprawdzono: $CHECKED, błędów: $ERRORS"

if [[ $ERRORS -gt 0 ]]; then
    if ! $FIX_MODE; then
        echo ""
        echo "Napraw hashe automatycznie: $0 --fix"
    fi
    exit 1
fi
