#!/usr/bin/env bash
# Install Formula/claudemon.rb from this checkout's HEAD commit with Homebrew, then style and audit
# the pristine formula. Used by CI's brew job and runnable on a Mac. Leaves Homebrew as it found it.
set -euo pipefail

export HOMEBREW_NO_AUTO_UPDATE=1 HOMEBREW_NO_INSTALL_UPGRADE=1 HOMEBREW_NO_INSTALL_CLEANUP=1
export HOMEBREW_NO_ANALYTICS=1 HOMEBREW_NO_ENV_HINTS=1

CHECKOUT=$(cd "$(dirname "$0")/.." && pwd)
WORK=$(mktemp -d)
LOCAL_TAP=local/claudemon
REAL_TAP=todddube/claudemon
# Only undo what this run did: an existing install or tap of the same name is not ours to remove.
HAD_FORMULA=0; brew list --formula claudemon >/dev/null 2>&1 && HAD_FORMULA=1
HAD_LOCAL=0; brew tap | grep -qx "$LOCAL_TAP" && HAD_LOCAL=1
HAD_REAL=0; brew tap | grep -qx "$REAL_TAP" && HAD_REAL=1

cleanup() {
  set +e
  if [ "$HAD_FORMULA" = 0 ]; then
    brew uninstall --force claudemon >/dev/null 2>&1
  fi
  if [ "$HAD_LOCAL" = 0 ]; then brew untap "$LOCAL_TAP" >/dev/null 2>&1; fi
  if [ "$HAD_REAL" = 0 ]; then brew untap "$REAL_TAP" >/dev/null 2>&1; fi
  rm -rf "$WORK"
}
trap cleanup EXIT

if [ "$HAD_FORMULA" = 1 ] || [ "$HAD_LOCAL" = 1 ] || [ "$HAD_REAL" = 1 ]; then
  echo "brew-check: claudemon is already installed or tapped here; remove it first" >&2
  exit 2
fi

# A clone of the checkout, with a branch at HEAD: the formula's head must name a branch that exists,
# and actions/checkout leaves a detached HEAD with no local main. The checkout itself is untouched.
git clone --no-local --quiet "$CHECKOUT" "$WORK/clone"
git -C "$WORK/clone" checkout --quiet -b ci-head "$(git -C "$CHECKOUT" rev-parse HEAD)"

# Install from a local tap whose formula reads head from the clone. tap-new --no-git keeps the files
# as written on disk (a tap of a git repo would use committed state only).
brew tap-new "$LOCAL_TAP" --no-git >/dev/null
DEST="$(brew --repository "$LOCAL_TAP")/Formula"
mkdir -p "$DEST"
sed -E "s|^  head .*|  head \"file://$WORK/clone\", branch: \"ci-head\", using: :git|" \
  "$CHECKOUT/Formula/claudemon.rb" > "$DEST/claudemon.rb"
grep -q "ci-head" "$DEST/claudemon.rb" || { echo "brew-check: head line not rewritten" >&2; exit 1; }

export CLAUDE_CONFIG_DIR="$WORK/claude"
mkdir -p "$CLAUDE_CONFIG_DIR" "$WORK/home"
brew install --HEAD "$LOCAL_TAP/claudemon"
HOME="$WORK/home" claudemon --version
# brew test loads the formula by its tap name, which needs the tap trusted (install did not).
if brew trust --help >/dev/null 2>&1; then brew trust "$LOCAL_TAP" || true; fi
brew test "$LOCAL_TAP/claudemon"

# Style and audit the pristine formula, tapped from the checkout's committed state.
brew tap "$REAL_TAP" "$CHECKOUT" >/dev/null
if brew trust --help >/dev/null 2>&1; then brew trust "$REAL_TAP" || true; fi
brew style "$REAL_TAP/claudemon"
brew audit --strict "$REAL_TAP/claudemon"
echo "brew-check: ok"
