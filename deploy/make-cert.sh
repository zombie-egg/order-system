#!/bin/sh
# Generates the self-signed certificate the web container serves on 443.
#
#   ./deploy/make-cert.sh              # uses the host's public IP
#   ./deploy/make-cert.sh shop.example # or a hostname
#
# Browsers will warn on a self-signed certificate; that is expected. Replace
# this with a CA-issued pair (or put Caddy in front) once a domain exists.
set -eu

CERT_DIR="$(cd "$(dirname "$0")" && pwd)/tls"
HOST="${1:-}"

if [ -z "$HOST" ]; then
    HOST="$(curl -fsS --max-time 5 http://metadata.tencentyun.com/latest/meta-data/public-ipv4 2>/dev/null || true)"
    [ -z "$HOST" ] && HOST="$(hostname -I 2>/dev/null | awk '{print $1}')"
    [ -z "$HOST" ] && { echo "Could not detect a host; pass one explicitly." >&2; exit 1; }
fi

# An IP has to go in subjectAltName as IP:, a hostname as DNS:, or browsers and
# fetch() reject the certificate outright.
case "$HOST" in
    *[0-9].[0-9]*[!a-zA-Z]*) SAN="IP:$HOST" ;;
    *[a-zA-Z]*) SAN="DNS:$HOST" ;;
    *) SAN="IP:$HOST" ;;
esac

mkdir -p "$CERT_DIR"
openssl req -x509 -nodes -newkey rsa:2048 -days 825 \
    -keyout "$CERT_DIR/server.key" \
    -out "$CERT_DIR/server.crt" \
    -subj "/CN=$HOST" \
    -addext "subjectAltName=$SAN" \
    -addext "basicConstraints=critical,CA:FALSE" \
    -addext "keyUsage=critical,digitalSignature,keyEncipherment" \
    -addext "extendedKeyUsage=serverAuth" 2>/dev/null

chmod 644 "$CERT_DIR/server.crt"
chmod 600 "$CERT_DIR/server.key"

echo "Wrote $CERT_DIR/server.{crt,key} for $HOST ($SAN)"
openssl x509 -in "$CERT_DIR/server.crt" -noout -subject -dates -ext subjectAltName
