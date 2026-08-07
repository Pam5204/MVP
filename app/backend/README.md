# Application Backend

This package owns the non-HTTP application layer:

- `services/` contains authentication/profile, destination/cache, bucket-list,
  review/rating, community CRUD/search/moderation, admin, validation/error, and
  RabbitMQ event coordination.
- `models.py`, `admin.py`, and `migrations/` contain Django persistence code.
- `settings.py`, `urls.py`, `asgi.py`, and `wsgi.py` configure Django.

Public API route definitions and request/response controllers remain in
the repository's top-level `api/` package. In the four-VM deployment, Gunicorn
on the API VM imports this backend package; the APP VM runs only Nginx and the
static files from `app/frontend`.

Registration and login have no direct-database mode. They always send a
private RabbitMQ command to `db.auth_consumer`, which performs password hashing
or verification and responds through a request-specific exclusive queue.

Destination reviews use a durable destination reference plus authenticated
user relationship. Community posts support the required experience/question
types, owner CRUD, displayed-text search, optional HTTP(S) picture references,
and administrator hide/restore controls. Optional comments, reactions, tags,
uploads, and pagination are intentionally not implemented.
