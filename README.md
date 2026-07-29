# DreamEscapes

DreamEscapes is a responsive destination-search application with account and
profile management, Geoapify search/details, a 24-hour DB-first cache,
ownership-protected bucket lists, an administrator dashboard, MySQL storage,
and RabbitMQ domain events/dead-letter handling.

## Project structure

```text
app/frontend/       Browser UI and frontend logic
app/backend/        Django configuration, models, and business services
api/                HTTP routes, controllers, CORS, and API tests
db/                 MySQL schema, procedures, setup, seeds, tests, DB consumer
mq/                 RabbitMQ topology, event contracts, setup, smoke tests
```

## Local development

Create an uncommitted `.env` from the relevant example values, then:

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```

The Django backend uses MySQL only. A real `GEOAPIFY_API_KEY` is required for
uncached destination searches. Registration and login always use the DB
authentication consumer through RabbitMQ; start that consumer before testing
those endpoints.

## Validation

```bash
python manage.py test
node --test app/frontend/tests/logic.test.js
python -m unittest discover -s db/tests -v
python manage.py check --deploy
```

Deployment/setup details live in:

- `app/backend/README.md`
- `api/README.md`
- `db/README.md`
- `mq/README.md`

`dependencies_install.sh` can configure ZeroTier, pinned Python dependencies,
the uncommitted environment values, role-specific setup scripts, service bind
addresses, and connectivity checks on the project VMs.
