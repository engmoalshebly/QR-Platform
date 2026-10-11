#!/usr/bin/env bash
# Build $QENTRY_ETC_DIR/certs/ca-bundle.pem = system roots + Cloudflare Origin CA.
#
# The API reaches Supabase through the public hostname, which Caddy answers on the
# private network using the Cloudflare Origin certificate.  Browsers never see that
# certificate (Cloudflare terminates TLS), and it is not in any public trust store,
# so the API containers need the Origin CA root explicitly.
set -euo pipefail
cd "$(dirname "$0")/../.."
ETC="${QENTRY_ETC_DIR:-/etc/qentry}"
IMAGE="${QENTRY_IMAGE:-qentry-api:local}"
tmp="$(mktemp -d)"; trap 'rm -rf "${tmp:?}"' EXIT

curl -fsS https://developers.cloudflare.com/ssl/static/origin_ca_rsa_root.pem -o "$tmp/rsa.pem"
curl -fsS https://developers.cloudflare.com/ssl/static/origin_ca_ecc_root.pem -o "$tmp/ecc.pem"
cat "$tmp/rsa.pem" "$tmp/ecc.pem" > "$tmp/roots.pem"

# Refuse to continue if the installed origin certificate does not chain to them.
openssl verify -CAfile "$tmp/roots.pem" "$ETC/certs/origin.crt" >/dev/null \
  || { echo "origin.crt does not chain to the Cloudflare Origin CA roots" >&2; exit 1; }

docker run --rm --entrypoint python "$IMAGE" -c 'import certifi; print(open(certifi.where()).read())' > "$tmp/system.pem"
cat "$tmp/system.pem" "$tmp/roots.pem" > "$ETC/certs/ca-bundle.pem"
chmod 644 "$ETC/certs/ca-bundle.pem"
echo "wrote $ETC/certs/ca-bundle.pem ($(grep -c BEGIN "$ETC/certs/ca-bundle.pem") certificates)"
