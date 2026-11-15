#!/bin/sh
set -eu

seed_dir=/app/media_seed/servicios
media_dir=/app/media/servicios

if [ ! -d "$seed_dir" ]; then
    echo "Missing committed service media seed: $seed_dir" >&2
    exit 1
fi

mkdir -p "$media_dir"

for seed_file in "$seed_dir"/*.png; do
    [ -f "$seed_file" ] || continue
    media_file="$media_dir/${seed_file##*/}"
    if [ ! -e "$media_file" ]; then
        cp "$seed_file" "$media_file"
    fi
done

exec "$@"
