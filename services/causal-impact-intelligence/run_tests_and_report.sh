#!/bin/sh
# Runs the suite and writes TEST_REPORT.md with the real output.
cd "$(dirname "$0")"
OUT=$(python3 -m unittest discover -s tests -v 2>&1); RC=$?
{ echo "# Test report"; echo; echo "Command: \`python3 -m unittest discover -s tests -v\`  (Python $(python3 --version 2>&1 | cut -d' ' -f2))"; echo "Exit code: $RC"; echo; echo '```'; echo "$OUT" | grep -v -e ResourceWarning -e '^  ' | tail -45; echo '```'; echo
  echo "Lint/type/build: none configured (pure stdlib, no build step). Coverage not measured."; } > TEST_REPORT.md
exit $RC
