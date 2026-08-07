# API Boundary

This folder owns the public HTTP API only:

- `urls.py` maps public URLs to API controllers.
- `views.py` validates HTTP requests and formats HTTP responses.
- `cors.py` applies API cross-origin response headers.
- `tests.py` contains API contract tests.

Business rules, persistence models, external-service integrations, RabbitMQ
coordination, and application logging belong in `app/backend`.

## Dedicated API VM

The API VM requires the complete repository because `api/views.py` calls the
models and services in `app/backend`. It does not serve the frontend. Run the
role installer after `.env` contains the DB VM and MQ VM addresses:

```bash
API_PORT=8000 bash api/setup_api.sh
```

The script installs the Python/MySQL client build dependencies, creates the
repository virtual environment, optionally stores the Geoapify key, validates
Django, and installs the `dreamescapes-api.service` Gunicorn service. Check it
with:

```bash
curl http://127.0.0.1:8000/api/health
sudo systemctl status dreamescapes-api --no-pager
```

The APP VM reaches this listener over the trusted ZeroTier network. Browsers
must open the APP VM URL, not the API VM URL.

## Route contract

```text
POST   /api/register
POST   /api/login
POST   /api/logout
GET    /api/profile
PUT    /api/profile
GET    /api/destinations/search
GET    /api/destinations/search-history
GET    /api/destinations/{place_id}
POST   /api/bucket-list
GET    /api/bucket-list
PUT    /api/bucket-list/{bucket_item_id}
DELETE /api/bucket-list/{bucket_item_id}
GET    /api/admin/users
PUT    /api/admin/users/{user_id}/role
PUT    /api/admin/users/{user_id}/status
GET    /api/admin/destinations
POST   /api/admin/destinations/{cache_id}/review
GET    /api/admin/audit-logs
```
