# Application Backend

This package owns the non-HTTP application layer:

- `services/` contains authentication/profile, destination/cache, bucket-list,
  admin, validation/error, and RabbitMQ event coordination.
- `models.py`, `admin.py`, and `migrations/` contain Django persistence code.
- `settings.py`, `urls.py`, `asgi.py`, and `wsgi.py` configure Django.

Public API route definitions and request/response controllers remain in
the repository's top-level `api/` package. In the four-VM deployment, Gunicorn
on the API VM imports this backend package; the APP VM runs only Nginx and the
static files from `app/frontend`.

Registration and login have no direct-database mode. They always send a
private RabbitMQ command to `db.auth_consumer`, which performs password hashing
or verification and responds through a request-specific exclusive queue.
