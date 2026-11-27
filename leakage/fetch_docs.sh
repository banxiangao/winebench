#!/usr/bin/env bash
# fetch_docs.sh <pages.tsv> <out dir> - download Microsoft documentation pages (repository <tab> path per line) from the
# public MicrosoftDocs repositories on GitHub into <out dir>/<repository>/<path>.  Pages already there are skipped.
# The branch of each repository is found by trying the usual names on the first page.
TSV=${1:?pages.tsv}; OUT=${2:?out dir}; declare -A BR
got=0; have=0; miss=0
while IFS=$'\t' read -r repo path; do
    [ -n "$repo" ] || continue
    f="$OUT/$repo/$path"; [ -s "$f" ] && { have=$((have+1)); continue; }
    mkdir -p "$(dirname "$f")"; ok=""
    for b in ${BR[$repo]:-docs main staging live}; do
        if curl -sfL --max-time 40 --retry 2 -o "$f.tmp" "https://raw.githubusercontent.com/MicrosoftDocs/$repo/$b/$path"; then mv "$f.tmp" "$f"; BR[$repo]=$b; ok=1; break; fi
    done
    rm -f "$f.tmp"
    if [ -n "$ok" ]; then got=$((got+1)); else miss=$((miss+1)); echo "MISSING $repo $path"; fi
done < "$TSV"
echo "pages: fetched $got, already there $have, missing $miss; branches: $(for r in "${!BR[@]}"; do printf '%s=%s ' "$r" "${BR[$r]}"; done)"
