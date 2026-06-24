#!/usr/bin/env bash
# sales.lifemakepartners.net を HTTPS化（Let's Encrypt / nginx）
set -e
DOMAIN=sales.lifemakepartners.net
export DEBIAN_FRONTEND=noninteractive
apt-get install -y certbot python3-certbot-nginx >/dev/null
certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos --register-unsafely-without-email --redirect
echo "==== OK-HTTPS-DONE ===="
echo " https://$DOMAIN/ が使えます"
