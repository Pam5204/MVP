# API Boundary

This folder owns the public HTTP API only:

- `urls.py` maps public URLs to API controllers.
- `views.py` validates HTTP requests and formats HTTP responses.
- `cors.py` applies API cross-origin response headers.
- `tests.py` contains API contract tests.

Business rules, persistence models, external-service integrations, RabbitMQ
coordination, and application logging belong in `app/backend`.

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
