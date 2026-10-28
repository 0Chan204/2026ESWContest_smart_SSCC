#!/usr/bin/env sh
set -eu
: "${IDF_PATH:?Activate ESP-IDF first}"
project_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
test_binary=$(mktemp /tmp/homevis-water-purifier-test.XXXXXX)
trap 'rm -f "$test_binary"' EXIT HUP INT TERM
cjson_dir="$IDF_PATH/components/json/cJSON"
"${CC:-cc}" -std=c11 -D_POSIX_C_SOURCE=200809L -Wall -Wextra -Werror \
    -fsanitize=address,undefined -fno-omit-frame-pointer -g \
    -I"$project_dir/main" -I"$cjson_dir" \
    "$project_dir/tests/test_model.c" "$project_dir/main/water_model.c" "$project_dir/main/water_led.c" \
    "$cjson_dir/cJSON.c" -lm -o "$test_binary"
"$test_binary"
