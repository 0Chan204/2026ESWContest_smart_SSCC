#!/usr/bin/env sh
set -eu
project_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
test_binary=$(mktemp /tmp/homevis-induction-test.XXXXXX)
trap 'rm -f "$test_binary"' EXIT HUP INT TERM
cc -std=c11 -Wall -Wextra -Werror -I"$project_dir/main" \
    "$project_dir/main/induction_model.c" "$project_dir/tests/test_model.c" -lm -o "$test_binary"
"$test_binary"
