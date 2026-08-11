#!/usr/bin/env bash
set -euo pipefail

base=/opt/market-intelligence/tools
browser_root="$base/browsers/chromium_headless_shell-1234"
tmp_dir=$(mktemp -d)
trap 'rm -rf "$tmp_dir"' EXIT
url=https://storage.googleapis.com/chrome-for-testing-public/151.0.7922.34/linux64/chrome-headless-shell-linux64.zip
total=120231126
parts=8
chunk=$(( (total + parts - 1) / parts ))

download_part() {
  local part=$1
  local start=$((part * chunk))
  local end=$((start + chunk - 1))
  if [ "$end" -ge "$total" ]; then end=$((total - 1)); fi
  local expected=$((end - start + 1))
  while true; do
    curl -4 -fsSL --retry 5 --connect-timeout 20 --max-time 180 --range "$start-$end" "$url" -o "$tmp_dir/part-$part" || true
    [ -f "$tmp_dir/part-$part" ] && [ "$(stat -c %s "$tmp_dir/part-$part")" -eq "$expected" ] && break
    rm -f "$tmp_dir/part-$part"
    sleep 1
  done
}
for part in $(seq 0 $((parts - 1))); do
  download_part "$part"
done
for part in $(seq 0 $((parts - 1))); do test "$(stat -c %s "$tmp_dir/part-$part")" -gt 0; done
cat $(for part in $(seq 0 $((parts - 1))); do printf '%s ' "$tmp_dir/part-$part"; done) > "$tmp_dir/chrome.zip"
test "$(stat -c %s "$tmp_dir/chrome.zip")" -eq "$total"
rm -rf "$browser_root"
install -d -m 0755 "$browser_root"
unzip -q "$tmp_dir/chrome.zip" -d "$browser_root"
chrome_path=$(find "$browser_root" -type f \( -name chrome-headless-shell -o -name headless_shell \) -perm -u+x | sort | tail -n 1)
test -n "$chrome_path"
ln -sfn "$(dirname "$chrome_path")" "$base/chromium"
chown -R marketintel:marketintel "$base"
echo "$chrome_path"
