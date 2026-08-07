# DreamEscapes Four-VM Deployment

This deployment keeps each MVP role on its own ZeroTier-connected Ubuntu VM.
Clone the complete repository on every VM, then run `dependencies_install.sh`
from the repository root. Use the same four IP addresses and service ports at
every prompt, but select **yes for only that VM's role**.

## Role selection

| VM | APP | API | DB | MQ |
| --- | --- | --- | --- | --- |
| APP/frontend VM | yes | no | no | no |
| API/Django VM | no | yes | no | no |
| DB/MySQL VM | no | no | yes | no |
| MQ/RabbitMQ VM | no | no | no | yes |

The APP and API ports can both be `8000` because they are on different VMs.
The APP-only path does not request or store MySQL, RabbitMQ, Django, or
Geoapify credentials.

## Required network paths

| Source | Destination | Default port | Purpose |
| --- | --- | --- | --- |
| User browser | APP VM | 8000 | Website |
| APP VM | API VM | 8000 | Nginx `/api/` proxy |
| API VM | DB VM | 3306 | Application data |
| API VM | MQ VM | 5672 | Authentication commands and domain events |
| DB VM | MQ VM | 5672 | Authentication consumer and replies |

Allow these paths only on the trusted network. The browser does not need
direct access to API/APP port 8000, MySQL port 3306, or AMQP port 5672.

## Installation order

1. Run the MQ role setup and use the intended RabbitMQ username/password.
2. Run the DB role setup with the same RabbitMQ credentials and the MySQL
   application password. The installer grants MySQL access to the API VM and
   a separate local account to the DB authentication consumer.
3. Run the API role setup. Configure the same DB and MQ credentials and enter
   the Geoapify key only on this VM.
4. Run the APP role setup. It needs only the API VM address and ports.

The installer can join ZeroTier first. If ZeroTier is already installed and
joined, answer no and use the existing network.

## Service verification

On the MQ VM:

```bash
sudo systemctl status rabbitmq-server --no-pager
sudo rabbitmqctl list_queues -p / name consumers messages_ready messages_unacknowledged
```

On the DB VM:

```bash
sudo systemctl status mysql --no-pager
sudo systemctl status dreamescapes-db-consumer --no-pager
```

On the API VM:

```bash
sudo systemctl status dreamescapes-api --no-pager
curl http://127.0.0.1:8000/api/health
```

On the APP VM, replace `8000` if a different APP port was selected:

```bash
sudo nginx -t
curl http://127.0.0.1:8000/
curl http://127.0.0.1:8000/api/health
```

The last command verifies the complete APP-to-API proxy path. Open only the
APP VM address in the browser, for example `http://APP_VM_IP:8000/`.

## Updating code

After pulling frontend changes on the APP VM, rerun `app/app_setup.sh` so the
new static files are copied to `/var/www/dreamescapes`. After pulling API or DB
consumer changes, restart the corresponding service:

```bash
sudo systemctl restart dreamescapes-api
sudo systemctl restart dreamescapes-db-consumer
```

Virtual environments do not retain old project source files; long-running
processes retain imported code until their service is restarted.
