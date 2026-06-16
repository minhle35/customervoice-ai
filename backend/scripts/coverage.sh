#!/usr/bin/env bash
# Run the full test suite and generate an HTML coverage report.
# Usage:
#   ./scripts/coverage.sh              # run all tests
#   ./scripts/coverage.sh tests/unit   # run a specific path
set -euo pipefail

REPORT_DIR="htmlcov"
TEST_PATH="${1:-tests}"

TEST_DATABASE_URL="${TEST_DATABASE_URL:-postgresql+psycopg2://postgres:postgres@127.0.0.1:5432/customer_voice_ai_test}"

export TEST_DATABASE_URL

uv run pytest "$TEST_PATH" \
    --cov \
    --cov-report=html:"$REPORT_DIR" \
    --cov-report=term-missing \
    "$@"

echo ""
echo "HTML report written to $(pwd)/$REPORT_DIR/index.html"
