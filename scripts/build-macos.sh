#!/usr/bin/env bash
# Build natively on the target Mac architecture; PyInstaller is not a cross compiler.
set -euo pipefail
project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root"
python_bin="${PYTHON:-python3}"
if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "Run this script on macOS (or use the build-desktop Actions workflow)." >&2
  exit 2
fi
if [[ "${1:-}" != "--skip-frontend" ]]; then
  (cd desktop-ui && pnpm install --frozen-lockfile && pnpm run build)
fi
test -f wenlint/desktop_ui/index.html
"$python_bin" scripts/collect-licenses.py
"$python_bin" -m PyInstaller \
  --noconfirm --clean --onedir --windowed \
  --name WenLint --specpath build --paths "$project_root" \
  --osx-bundle-identifier org.wenlint.desktop \
  --collect-all webview \
  --add-data "$project_root/build/third-party-licenses:third-party-licenses" \
  --add-data "$project_root/wenlint/desktop_ui:wenlint/desktop_ui" \
  --add-data "$project_root/LICENSE:." \
  scripts/wenlint_desktop_entry.py
echo "Built: $project_root/dist/WenLint.app (not notarized)"
