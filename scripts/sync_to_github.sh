#!/usr/bin/env bash
set -euo pipefail

REPO_URL="${1:-https://github.com/Diamondunn/stock_agent.git}"
BRANCH="${2:-main}"
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK_DIR="$(mktemp -d /tmp/stock_agent_sync.XXXXXX)"
CLONE_DIR="$WORK_DIR/repo"

echo "Cloning $REPO_URL ..."
git clone --branch "$BRANCH" "$REPO_URL" "$CLONE_DIR"

echo "Copying safe project files ..."
rsync -a "$SRC_DIR/app" "$CLONE_DIR/"
rsync -a "$SRC_DIR/web" "$CLONE_DIR/"
rsync -a "$SRC_DIR/scripts" "$CLONE_DIR/"
rsync -a "$SRC_DIR/tests" "$CLONE_DIR/"
if [[ -d "$SRC_DIR/.github" ]]; then
  rsync -a "$SRC_DIR/.github" "$CLONE_DIR/"
fi

for file in \
  README.md \
  DEVELOPMENT.md \
  ROADMAP.md \
  STRUCTURE.md \
  .gitignore \
  .env.example \
  pytest.ini \
  requirements.txt
do
  if [[ -f "$SRC_DIR/$file" ]]; then
    cp "$SRC_DIR/$file" "$CLONE_DIR/$file"
  fi
done

cd "$CLONE_DIR"

echo "Staging safe files ..."
git add \
  README.md \
  DEVELOPMENT.md \
  ROADMAP.md \
  STRUCTURE.md \
  .gitignore \
  .env.example \
  pytest.ini \
  requirements.txt \
  .github \
  app \
  web \
  scripts \
  tests

if git diff --cached --quiet; then
  echo "No changes to upload."
  exit 0
fi

git commit -m "Improve project structure and docs"
git push origin "$BRANCH"

echo "Uploaded latest project files."
echo "Temporary clone kept at: $CLONE_DIR"
