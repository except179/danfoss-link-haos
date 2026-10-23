#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
task_lint_dir=$(mktemp -d)
curl --fail --silent --show-error --location \
  https://github.com/rhysd/actionlint/releases/download/v1.7.12/actionlint_1.7.12_linux_amd64.tar.gz \
  --output "$task_lint_dir/actionlint.tar.gz"
printf '%s  %s\n' 8aca8db96f1b94770f1b0d72b6dddcb1ebb8123cb3712530b08cc387b349a3d8 "$task_lint_dir/actionlint.tar.gz" | sha256sum -c -
tar -xzf "$task_lint_dir/actionlint.tar.gz" -C "$task_lint_dir" actionlint
"$task_lint_dir/actionlint" -shellcheck= -pyflakes= .github/workflows/validate.yaml
