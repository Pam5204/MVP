# DreamEscapes Database

This folder owns the MySQL schema, data-integrity rules, stored procedures,
seed data, database assertions, and the DB-role authentication consumer.

## Files

- `DreamEscapes.sql` creates the database, five required tables, indexes,
  foreign keys, uniqueness rules, and all checklist procedures.
- `setup_mysql.sh` installs and starts MySQL, prepares the DB-consumer Python
  and Django migration dependencies, creates/updates the application DB user
  and permissions, loads the schema, synchronizes Django's migration history,
  and can optionally load demo records.
- `seed_data.sql` provides one user and one administrator with valid bcrypt
  hashes for local demonstrations.
- `test_schema.sql` runs rollback-safe assertions for users, duplicate email,
  bucket ownership/duplicates, cache freshness/expiry, history, and audit data.
- `auth_consumer.py` uses mysqlclient to process registration/login commands
  from RabbitMQ on the DB VM and never returns or logs password material.
- `db.env.example` documents required deployment variables without secrets.

## Setup

From the repository root on the DB VM:

```bash
DB_USER=dream_app \
DB_APP_HOST='10.%' \
DB_PASSWORD='supply-outside-git' \
LOAD_SEED_DATA=yes \
bash db/setup_mysql.sh
```

Use a narrower `DB_APP_HOST` whenever the App/API VM address is known. The
script grants row access plus `EXECUTE`, `CREATE ROUTINE`, and `ALTER ROUTINE`
on the DreamEscapes database. The routine permissions let the documented
rollback-safe schema assertions create and remove their test procedure.

Run the database assertions:

```bash
mysql --user=dream_app --password DreamEscapes < db/test_schema.sql
```

Start the production MQ authentication consumer after loading environment
variables:

```bash
python -m db.auth_consumer
```

The Django backend always uses MySQL. Configure the `DB_*` variables from
`db.env.example` for local development, tests, and deployment. The setup
script runs `migrate --fake-initial` as the MySQL administrator: Django creates
its own framework tables while recognizing the five application tables that
`DreamEscapes.sql` already created.
