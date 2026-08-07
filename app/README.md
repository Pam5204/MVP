# App Service

The dedicated APP VM serves only the browser interface from `frontend/`.
`app_setup.sh` installs Nginx, copies those static assets to
`/var/www/dreamescapes`, and proxies browser requests under `/api/` to the
separate API VM. Keeping the proxy on the APP origin prevents session-cookie
failures between different ZeroTier IP addresses.
The tracked Nginx site template lives at
`frontend/nginx/dreamescapes.conf.template` beside the frontend it serves.

Run it directly with the API VM address when the main installer is not used:

```bash
API_HOST=10.0.0.12 API_PORT=8000 APP_LISTEN_PORT=8000 \
  bash app/app_setup.sh
```

`backend/` contains Django configuration, models, and business services, but
that Python package executes inside the API VM process. Its folder ownership
does not require the APP and API roles to share a VM. The top-level `api/`
folder remains limited to the HTTP boundary.
