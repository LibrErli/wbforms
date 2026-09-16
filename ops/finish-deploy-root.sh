#!/bin/sh
set -eu

DOMAIN="sax-besucherbuch.knowledge.wiki"
SITE="sax-besucherbuch.conf"

if [ "$(id -u)" -ne 0 ]; then
    echo "Run this script with sudo." >&2
    exit 1
fi

a2enmod proxy_http headers ssl rewrite
a2ensite "$SITE"
apache2ctl configtest
systemctl reload apache2

certbot --apache \
    --domain "$DOMAIN" \
    --redirect \
    --non-interactive \
    --agree-tos \
    --email info@mail.knowledge.wiki \
    --keep-until-expiring

apache2ctl configtest
systemctl reload apache2

echo "Apache and TLS are active for https://$DOMAIN/"
