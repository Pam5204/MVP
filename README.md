# DreamEscapes

DreamEscapes is a responsive destination-search application with account and
profile management, Geoapify search/details, a 24-hour DB-first cache,
ownership-protected bucket lists, persisted destination reviews and ratings,
a searchable community discussion board, administrator moderation, MySQL
storage, and RabbitMQ centralized final-feature logging/dead-letter handling.

## Project structure

```text
app/frontend/       Browser UI and frontend logic
app/backend/        Django configuration, models, and API business services
api/                HTTP routes, controllers, CORS, and API tests
db/                 MySQL schema, procedures, setup, seeds, tests, DB consumer
mq/                 RabbitMQ topology, event contracts, setup, smoke tests
```

## Four-VM runtime

The deployed request path is:

```text
Browser -> APP VM (Nginx/static UI) -> API VM (Django/Gunicorn)
                                      |-> DB VM (MySQL)
                                      |-> MQ VM (RabbitMQ)
DB VM auth consumer --------------------> MQ VM
```

Nginx proxies `/api/` so browser sessions stay on the APP origin. Django and
the `api/` package run only on the API VM. MySQL and the authentication
consumer run on the DB VM, and RabbitMQ runs on the MQ VM. See
`docs/four-vm-deployment.md` for installation choices, ports, and verification.

## Local API development

Create an uncommitted `.env` from the relevant example values, then:

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver 127.0.0.1:8000
```

The Django API uses MySQL only. A real `GEOAPIFY_API_KEY` is required for
uncached destination searches. Registration and login always use the DB
authentication consumer through RabbitMQ; start that consumer before testing
those endpoints. Use the APP Nginx setup for browser testing so its `/api/`
requests are proxied to this process.

## Validation

```bash
python manage.py test
node --test app/frontend/tests/logic.test.js
python -m unittest discover -s db/tests -v
python manage.py check --deploy
```

The final-feature MQ evidence file is append-only JSON Lines on the MQ VM:
`/var/log/dreamescapes/final_features.jsonl`. Review and community API mutation
responses return the matching `correlation_id` used in that log.

Deployment/setup details live in:

- `app/backend/README.md`
- `api/README.md`
- `db/README.md`
- `mq/README.md`
- `docs/four-vm-deployment.md`

`dependencies_install.sh` can configure ZeroTier, pinned Python dependencies,
the uncommitted environment values, role-specific setup scripts, service bind
addresses, and connectivity checks on the project VMs.
