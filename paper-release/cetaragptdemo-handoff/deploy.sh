#!/usr/bin/env bash
# ============================================================================
# CetaraGPT deployment script for Ubuntu/Debian or Oracle/RHEL servers.
# Installs Python deps, sets up systemd + nginx + Let's Encrypt.
#
# Run AS ROOT on the target server, after uploading cetara-deploy.tgz to /tmp/:
#     sudo bash /tmp/deploy.sh
#
# Prerequisites:
#   - /tmp/cetara-deploy.tgz exists (built by pack step on your laptop)
#   - DNS A record for cetara.jinyue-jiang.com points to this server's IP
#   - Cloudflare proxy is OFF (gray cloud)
#   - Oracle Cloud VCN security list allows tcp/80 and tcp/443 from 0.0.0.0/0
#
# Idempotent - safe to re-run.
# ============================================================================
set -euo pipefail

# Configuration
# SUBDOMAIN: the public hostname this backend will serve.
# CHANGE THIS to a subdomain you control before deploying.
# A DNS A record for this name must already point at this server's public IP.
# You can also override at the command line:  SUBDOMAIN=foo.example.com sudo -E bash deploy.sh
SUBDOMAIN="${SUBDOMAIN:-cetara.example.com}"
INSTALL_DIR="/opt/cetaragpt"
SERVICE_USER="cetara"
ENV_FILE="/etc/cetaragpt.env"
SERVICE_FILE="/etc/systemd/system/cetaragpt.service"
NGINX_FILE="/etc/nginx/conf.d/cetara.conf"
TARBALL="/tmp/cetara-deploy.tgz"

log()  { printf "\n==> %s\n" "$*"; }
ok()   { printf "    ok: %s\n" "$*"; }
warn() { printf "    warn: %s\n" "$*"; }
fail() { printf "\nFAIL: %s\n" "$*" >&2; exit 1; }

# 1. Pre-flight: OS detect + tarball check
log "Pre-flight checks"
[[ $EUID -eq 0 ]] || fail "Must run as root (use sudo)"
[[ -f "$TARBALL" ]] || fail "Tarball not found at $TARBALL - scp it up first"

# Identify OS family
if [[ -f /etc/os-release ]]; then
  # shellcheck disable=SC1091
  . /etc/os-release
  OS_ID="${ID:-unknown}"
  OS_LIKE="${ID_LIKE:-}"
else
  fail "Cannot determine OS (no /etc/os-release)"
fi
if [[ "$OS_ID" == "ubuntu" || "$OS_ID" == "debian" || "$OS_LIKE" == *debian* ]]; then
  OS_FAMILY="debian"
elif [[ "$OS_ID" =~ ^(ol|rhel|centos|rocky|alma)$ || "$OS_LIKE" == *rhel* ]]; then
  OS_FAMILY="rhel"
else
  fail "Unsupported OS: $OS_ID (only Ubuntu/Debian and Oracle/RHEL supported)"
fi
ok "OS detected: $OS_ID ($OS_FAMILY family)"

# Tarball sanity
if tar tzf "$TARBALL" | grep -qE "(\.ipynb|\.docx|\.xlsx|results/|figures/|paper_at_a_glance)"; then
  fail "Tarball contains forbidden files - rebuild it"
fi
if gunzip -c "$TARBALL" | grep -aoE "AIzaSy[A-Za-z0-9_-]{20,}" | head -1 | grep -q .; then
  fail "Tarball contains an API-key string - rebuild it"
fi
ok "Tarball is clean"

# DNS check
ip_resolved="$(getent hosts "$SUBDOMAIN" | awk '{print $1}' | head -1 || true)"
if [[ -z "$ip_resolved" ]]; then
  warn "$SUBDOMAIN doesn't resolve yet. certbot will fail at step 11."
  read -rp "  Continue anyway? [y/N] " ans
  [[ "$ans" == "y" || "$ans" == "Y" ]] || fail "Aborted - fix DNS first"
fi
ok "DNS lookup OK ($SUBDOMAIN → $ip_resolved)"

# 2. Prompt for secrets
log "Configuration prompts"

existing_key=""
if [[ -f "$ENV_FILE" ]]; then
  existing_key="$(grep -E '^GOOGLE_API_KEY=' "$ENV_FILE" | cut -d= -f2- || true)"
fi
if [[ -n "$existing_key" ]]; then
  read -rp "  Existing API key found in $ENV_FILE - keep it? [Y/n] " ans
  if [[ "$ans" != "n" && "$ans" != "N" ]]; then
    GEMINI_KEY="$existing_key"
  else
    GEMINI_KEY=""
  fi
fi
if [[ -z "${GEMINI_KEY:-}" ]]; then
  read -rsp "  Enter your Gemini API key (starts with AIzaSy...): " GEMINI_KEY
  echo
fi
[[ "$GEMINI_KEY" =~ ^AIzaSy[A-Za-z0-9_-]{30,40}$ ]] || fail "Key format looks wrong"

read -rp "  Enter your email for Let's Encrypt: " LE_EMAIL
[[ "$LE_EMAIL" =~ ^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$ ]] || fail "Invalid email"
ok "Inputs validated"

# 3. Install packages
log "Installing system packages"
if [[ "$OS_FAMILY" == "debian" ]]; then
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq
  apt-get install -y -qq python3 python3-venv python3-pip python3-dev \
                          nginx certbot python3-certbot-nginx \
                          curl ca-certificates iptables-persistent > /dev/null
  PY=python3
else
  dnf install -y python3.11 python3.11-pip python3.11-devel \
                 nginx certbot python3-certbot-nginx curl > /dev/null
  PY=python3.11
fi

# Sanity-check Python version (langchain 1.x needs 3.10+)
py_ver="$($PY -c 'import sys; print(f"{sys.version_info[0]}.{sys.version_info[1]}")')"
maj="${py_ver%.*}"; min="${py_ver#*.}"
if (( maj < 3 || (maj == 3 && min < 10) )); then
  fail "Python 3.10+ required, found $py_ver"
fi
ok "Packages installed (Python $py_ver)"

# 4. Create service user
log "Creating service user '$SERVICE_USER'"
if ! id "$SERVICE_USER" &>/dev/null; then
  useradd --system --home-dir "$INSTALL_DIR" --shell /usr/sbin/nologin "$SERVICE_USER" 2>/dev/null \
    || useradd --system --home-dir "$INSTALL_DIR" --shell /sbin/nologin "$SERVICE_USER"
  ok "Created user '$SERVICE_USER'"
else
  ok "User already exists"
fi

# 5. Extract code
log "Extracting code to $INSTALL_DIR"
mkdir -p "$INSTALL_DIR"
tar xzf "$TARBALL" -C "$INSTALL_DIR" --strip-components=1
chown -R "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR"
ok "Code extracted"

# 6. Python venv + pip install
log "Creating Python venv (this takes ~2 minutes)"
sudo -u "$SERVICE_USER" "$PY" -m venv "$INSTALL_DIR/venv"
sudo -u "$SERVICE_USER" "$INSTALL_DIR/venv/bin/pip" install -U pip -q
sudo -u "$SERVICE_USER" "$INSTALL_DIR/venv/bin/pip" install \
    -r "$INSTALL_DIR/requirements.txt" -q
ok "Dependencies installed"

# 7. API key file (root-only)
log "Writing API key to $ENV_FILE"
umask 077
printf "GOOGLE_API_KEY=%s\n" "$GEMINI_KEY" > "$ENV_FILE"
chmod 600 "$ENV_FILE"
chown root:root "$ENV_FILE"
unset GEMINI_KEY
ok "API key stored (root:root, mode 0600)"

# 8. systemd unit
log "Installing systemd unit"
cat > "$SERVICE_FILE" <<EOF
[Unit]
Description=CetaraGPT Flask demo (agentic RAG over PFAS-membrane dataset)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$SERVICE_USER
Group=$SERVICE_USER
WorkingDirectory=$INSTALL_DIR
EnvironmentFile=$ENV_FILE
ExecStart=$INSTALL_DIR/venv/bin/gunicorn \\
    --bind 127.0.0.1:5000 \\
    --workers 1 --threads 4 --timeout 180 \\
    --access-logfile - --error-logfile - \\
    demo_server:app
Restart=on-failure
RestartSec=5

NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ReadWritePaths=$INSTALL_DIR
ProtectHome=true
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable cetaragpt > /dev/null 2>&1 || true
systemctl restart cetaragpt
sleep 3
if systemctl is-active --quiet cetaragpt; then
  ok "cetaragpt service is running"
else
  log "Service logs (last 30 lines):"
  journalctl -u cetaragpt --no-pager -n 30
  fail "Service failed to start"
fi

if curl -sf http://127.0.0.1:5000/api/tools | grep -q "filter_records"; then
  ok "Flask responds on 127.0.0.1:5000"
else
  fail "Flask not responding locally"
fi

# 9. Nginx server block
log "Writing Nginx server block"
# Debian/Ubuntu put nginx confs in conf.d AND sites-enabled - conf.d works on both.
mkdir -p /var/www/letsencrypt
cat > "$NGINX_FILE" <<EOF
# CetaraGPT reverse proxy - don't touch other server blocks here.
server {
    listen 80;
    listen [::]:80;
    server_name $SUBDOMAIN;

    location /.well-known/acme-challenge/ {
        root /var/www/letsencrypt;
    }
    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_http_version 1.1;
        proxy_set_header Host              \$host;
        proxy_set_header X-Real-IP         \$remote_addr;
        proxy_set_header X-Forwarded-For   \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 180s;
        client_max_body_size 64k;
    }
}
EOF
# NOTE: an earlier version of this script removed the default Ubuntu nginx
# vhost (/etc/nginx/sites-enabled/default) to free port 80. That is UNSAFE
# on shared servers where other sites may live in the default vhost. We
# instead rely on the per-subdomain server_name in the new conf above to
# steer matching requests, and leave the default vhost alone. If the new
# subdomain doesn't get served correctly after this step, inspect:
#   sudo nginx -T | grep -E 'server_name|listen'
# to confirm only one server block claims your SUBDOMAIN.
if [[ "$OS_FAMILY" == "debian" && -f /etc/nginx/sites-enabled/default ]]; then
  warn "Default Ubuntu/Debian vhost found at /etc/nginx/sites-enabled/default - LEAVING IT ALONE."
  warn "If $SUBDOMAIN is served from the default vhost instead of cetara.conf,"
  warn "you may need to delete or edit it manually after verifying nothing else uses it."
fi
nginx -t > /dev/null 2>&1 || { nginx -t; fail "Nginx config invalid"; }
systemctl reload nginx 2>/dev/null || systemctl restart nginx
ok "Nginx HTTP block live"

# 10. Firewall (OS-specific)
log "10/12 Firewall configuration"
if [[ "$OS_FAMILY" == "debian" ]]; then
  # Oracle Cloud Ubuntu ships iptables with a REJECT rule on chain INPUT.
  # Insert ACCEPT rules at the top so they sit above the REJECT.
  for port in 80 443; do
    if ! iptables -C INPUT -p tcp --dport "$port" -j ACCEPT 2>/dev/null; then
      iptables -I INPUT 1 -p tcp --dport "$port" -j ACCEPT
    fi
  done
  # Persist across reboots (iptables-persistent installed in step 3)
  if command -v netfilter-persistent &>/dev/null; then
    netfilter-persistent save > /dev/null 2>&1 || true
  fi
  ok "iptables: HTTP + HTTPS allowed on this instance"
  warn "Oracle Cloud also has a VCN-level security list."
  warn "If certbot fails at step 11, check VCN ingress rules for ports 80, 443."
else
  setsebool -P httpd_can_network_connect 1 2>/dev/null && \
    ok "SELinux: httpd_can_network_connect ON" || \
    warn "SELinux setbool skipped (not enforcing)"
  firewall-cmd --permanent --add-service=http  > /dev/null
  firewall-cmd --permanent --add-service=https > /dev/null
  firewall-cmd --reload                        > /dev/null
  ok "firewalld: HTTP + HTTPS open"
fi

# 11. TLS via Let's Encrypt
log "11/12 Requesting TLS certificate via certbot"
if certbot --nginx -d "$SUBDOMAIN" --redirect --agree-tos \
       -m "$LE_EMAIL" --non-interactive; then
  ok "TLS certificate obtained, Nginx now serves HTTPS with redirect"
else
  warn "certbot failed. Most common causes:"
  warn "  1) DNS for $SUBDOMAIN doesn't resolve to this server yet"
  warn "  2) Cloudflare proxy is still ON (must be gray cloud during issue)"
  warn "  3) Oracle Cloud VCN security list doesn't allow tcp/80"
  warn ""
  warn "The app IS running on plain HTTP at http://$SUBDOMAIN/ - retry with:"
  warn "  sudo certbot --nginx -d $SUBDOMAIN --redirect --agree-tos -m $LE_EMAIL --non-interactive"
  fail "TLS setup failed (but service is up; fix the cause and retry certbot)"
fi

# 12. End-to-end verification
log "12/12 End-to-end verification from the public URL"
sleep 2

n_tools="$(curl -sf "https://$SUBDOMAIN/api/tools" | grep -oE '"name"' | wc -l)"
[[ "$n_tools" == "5" ]] || fail "Expected 5 tools, got $n_tools"
ok "5/5 tools exposed at https://$SUBDOMAIN/api/tools"

if curl -sfL "https://$SUBDOMAIN/" | grep -q "CetaraGPT"; then
  ok "demo.html serves at https://$SUBDOMAIN/"
else
  fail "Demo page not serving"
fi

cat <<EOF

CetaraGPT deployed successfully.

   Open:        https://$SUBDOMAIN/
   Logs:        sudo journalctl -u cetaragpt -f
   Restart:     sudo systemctl restart cetaragpt
   Rotate key:  sudo nano $ENV_FILE && sudo systemctl restart cetaragpt

   To roll back:
     sudo systemctl disable --now cetaragpt
     sudo rm -rf $INSTALL_DIR
     sudo rm $ENV_FILE $SERVICE_FILE $NGINX_FILE
     sudo systemctl daemon-reload
     sudo systemctl reload nginx

EOF
