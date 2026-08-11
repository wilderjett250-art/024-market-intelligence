#!/usr/bin/env bash
set -euo pipefail

base=/opt/market-intelligence/tools
node_version=20.19.3
node_root="$base/node"
package_root="$base/douyin-sync"
browsers="$base/browsers"

install -d -m 0755 "$base" "$package_root" "$browsers"
if [ ! -x "$node_root/bin/node" ]; then
  tmp_dir=$(mktemp -d)
  trap 'rm -rf "$tmp_dir"' EXIT
  curl -4 -fsSL "https://nodejs.org/dist/v${node_version}/node-v${node_version}-linux-x64.tar.xz" -o "$tmp_dir/node.tar.xz"
  curl -4 -fsSL "https://nodejs.org/dist/v${node_version}/SHASUMS256.txt" -o "$tmp_dir/SHASUMS256.txt"
  expected=$(awk '$2 == "node-v'"${node_version}"'-linux-x64.tar.xz" { print $1 }' "$tmp_dir/SHASUMS256.txt")
  actual=$(sha256sum "$tmp_dir/node.tar.xz" | awk '{ print $1 }')
  test -n "$expected" && test "$expected" = "$actual"
  tar -xJf "$tmp_dir/node.tar.xz" -C "$tmp_dir"
  rm -rf "$node_root"
  mv "$tmp_dir/node-v${node_version}-linux-x64" "$node_root"
  trap - EXIT
  rm -rf "$tmp_dir"
fi

export PATH="$node_root/bin:$PATH"

if [ ! -f "$package_root/node_modules/playwright/package.json" ]; then
  printf '{"private":true}\n' > "$package_root/package.json"
  "$node_root/bin/npm" --prefix "$package_root" install --omit=optional --no-audit --no-fund playwright@1.62.1
fi

browser_root="$browsers/chromium_headless_shell-1234"
if [ ! -x "$base/chromium/chrome-headless-shell" ]; then
  browser_tmp=$(mktemp -d)
  trap 'rm -rf "$browser_tmp"' EXIT
  curl -4 -fsSL --retry 3 --connect-timeout 20 "https://storage.googleapis.com/chrome-for-testing-public/151.0.7922.34/linux64/chrome-headless-shell-linux64.zip" -o "$browser_tmp/chrome.zip"
  rm -rf "$browser_root"
  install -d -m 0755 "$browser_root"
  unzip -q "$browser_tmp/chrome.zip" -d "$browser_root"
  trap - EXIT
  rm -rf "$browser_tmp"
fi
chrome_path=$(find "$browser_root" -type f \( -name chrome-headless-shell -o -name headless_shell \) -perm -u+x | sort | tail -n 1)
test -n "$chrome_path"
ln -sfn "$(dirname "$chrome_path")" "$base/chromium"

chown -R marketintel:marketintel "$base"
chmod 0755 "$base/chromium"
echo "Douyin browser runtime ready: $chrome_path"
