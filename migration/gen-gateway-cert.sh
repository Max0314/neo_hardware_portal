#!/usr/bin/env bash
# 生成带 SAN（IP/localhost）的自签网关证书，减少「证书无效」类告警
# 用法: bash migration/gen-gateway-cert.sh [IP或域名，默认 192.168.1.77]
set -eu

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
CERT_DIR="$ROOT/gateway/certs"
CN="${1:-192.168.1.77}"

mkdir -p "$CERT_DIR"
CFG="$(mktemp)"
trap 'rm -f "$CFG"' EXIT

cat >"$CFG" <<EOF
[req]
default_bits = 2048
prompt = no
default_md = sha256
distinguished_name = dn
x509_extensions = v3

[dn]
CN = ${CN}
O = HardwareRD
C = CN

[v3]
subjectAltName = @alt

[alt]
DNS.1 = localhost
DNS.2 = ${CN}
IP.1 = 127.0.0.1
EOF

# 若 CN 形如 IP，写入 SAN
if printf '%s' "$CN" | grep -qE '^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$'; then
  echo "IP.2 = ${CN}" >> "$CFG"
fi

openssl req -x509 -nodes -days 825 -newkey rsa:2048 \
  -keyout "$CERT_DIR/server.key" \
  -out "$CERT_DIR/server.crt" \
  -config "$CFG" -extensions v3

echo "已生成: $CERT_DIR/server.crt  $CERT_DIR/server.key  (CN/SAN: ${CN})"
echo "重启网关: docker compose up -d gateway"
