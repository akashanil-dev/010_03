# Deploying TallyTime at tallytime.akashanil.dev

These steps put TallyTime on an Oracle Cloud **Always Free Ampere A1** VM (4 ARM cores, 24 GB RAM, Ubuntu 24.04) behind HTTPS.
The result: one web app, one worker that reads documents one check at a time, Ollama running Granite on the same machine,
and Caddy in front with an automatic Let's Encrypt certificate.

```
Internet ──HTTPS──► Caddy :443 ──► tallytime-web (uvicorn, 127.0.0.1:8000) ──► SQLite (data/tally.db)
                                                                                   ▲
                                   tallytime-worker ── reader process (Docling) ───┘──► Ollama (127.0.0.1:11434)
```

Allow about an hour. Most of that is downloads.

---

## 1. Before you start

### Oracle Cloud
1. Create the VM: **Ampere A1 Flex, 4 OCPU, 24 GB**, image **Canonical Ubuntu 24.04 (aarch64)**, at least **100 GB boot volume** (models and Python packages take about 15 GB). Add your SSH public key.
2. Give it a **reserved public IP** (Networking → IP management), so the address survives a restart.
3. Open the ports in the **VCN Security List** (or Network Security Group) attached to the VM's subnet. Add ingress rules for source `0.0.0.0/0`:
   - TCP **80** (Let's Encrypt and the redirect to HTTPS)
   - TCP **443** (the site)
   - UDP **443** (HTTP/3, optional)

   `setup.sh` also opens these in the VM's own iptables firewall. Oracle's Ubuntu images block them there by default, and that's the usual reason a new site can't be reached.

### DNS
Add an **A record**: `tallytime` → the VM's public IP, on the DNS for `akashanil.dev`. Wait until `dig +short tallytime.akashanil.dev` prints the IP.
`.dev` domains only work over HTTPS. Caddy gets the certificate automatically once DNS points at the VM.

### Oracle Email Delivery (email)
TallyTime sends its emails (sign-up confirmation, password reset, invitations, optional "check finished") through OCI Email
Delivery, in the same Oracle account as the VM. It adds no branding to emails. Do these steps **in the same region as the VM**
(top-right region menu in the OCI console).

1. **Email domain.** Menu → **Developer Services → Email Delivery → Email Domains → Create Email Domain**: `akashanil.dev`, in your compartment.
2. **DKIM** (proves the emails really come from you). Open the email domain → **DKIM → Add DKIM**, selector for example `tallytime-202610`
   (it must be unique; a date suffix makes later key rotation easy) → **Generate DKIM Record**. Add the **CNAME** record it shows to the
   DNS of `akashanil.dev`, exactly as given. Back in the console, the DKIM status turns **Active** once DNS has updated (minutes to a few hours).
3. **SPF** (lists who may send for the domain). Add a **TXT** record on `akashanil.dev` for the VM's region:
   - Asia/Pacific (Mumbai, Hyderabad, Singapore…): `v=spf1 include:ap.rp.oracleemaildelivery.com ~all`
   - Europe: `v=spf1 include:eu.rp.oracleemaildelivery.com ~all`
   - Americas: `v=spf1 include:rp.oracleemaildelivery.com ~all`

   A domain can have only **one** SPF record: if `akashanil.dev` already has a `v=spf1 …` TXT record (for example for your own mailbox),
   add the `include:…` part to that record instead of creating a second one. The email domain page shows whether SPF is configured.
4. **DMARC** (optional but recommended; tells mailbox providers what to do with failures). TXT record on `_dmarc.akashanil.dev`:
   `v=DMARC1; p=none; rua=mailto:privacy@akashanil.dev`
5. **Approved sender.** Email Delivery → **Approved Senders → Create Approved Sender**: `no-reply@akashanil.dev`. Emails can only be sent
   from approved senders, so this must match `MAIL_FROM` exactly.
6. **SMTP credentials.** Profile menu (top right) → **My profile → SMTP Credentials → Generate SMTP Credentials**, description `tallytime`.
   Copy the **username** (a long `ocid1.user…` string) and the **password**: the password is shown **only once**.
   The account administrator can send straight away; any other user needs an IAM policy such as
   `Allow group <group> to use email-family in compartment <compartment>`.
7. **SMTP server address.** Email Delivery → **Configuration**: note the **public endpoint**, for example
   `smtp.email.ap-mumbai-1.oci.oraclecloud.com`. Use port **587** (STARTTLS).

The Always Free allowance is reported as 3,000 emails a month; check your tenancy's actual limit under **Governance → Limits, Quotas and
Usage → Email Delivery**, and request an increase there if needed. "Check finished" emails are off by default, and each person turns them
on themselves, so sign-ups and password resets are most of the volume.

### Cloudflare Turnstile (bot check on sign-up)
Cloudflare dashboard → **Turnstile → Add widget**: hostname `tallytime.akashanil.dev`, mode *Managed*. Note the **site key** and **secret key**. It's free and works even though your DNS is not on Cloudflare.

### A mailbox for privacy requests
The privacy policy and terms give `privacy@akashanil.dev` as the contact address. Make sure it receives mail, or change it in `static/privacy.html`, `static/terms.html` and `CONTACT_EMAIL`.

---

## 2. Install

SSH into the VM, then:

```bash
git clone https://github.com/akashanil-dev/010_03.git /tmp/tallytime
sudo bash /tmp/tallytime/deploy/setup.sh
```

The script:
- installs updates, fail2ban, Caddy and Ollama, and pulls `granite4:micro`;
- opens ports 80 and 443 in iptables;
- creates a `tallytime` system user and puts the app in `/opt/tallytime`, with a Python 3.12 environment;
- downloads the Docling models and warms up OCR;
- creates `/opt/tallytime/.env` with fresh Web Push keys;
- installs and starts the `tallytime-web` and `tallytime-worker` services and Caddy;
- keeps logs for 30 days and sets up a nightly backup of **account data only**;
- starts reading the demo shipments in the background, so demos are instant afterwards (about an hour).

## 3. Configure

```bash
sudo -u tallytime nano /opt/tallytime/.env
```

Set at least:

```ini
PUBLIC_URL=https://tallytime.akashanil.dev
SMTP_HOST=<public endpoint, e.g. smtp.email.ap-mumbai-1.oci.oraclecloud.com>
SMTP_PORT=587
SMTP_USER=<SMTP credentials username, the ocid1.user… string>
SMTP_PASSWORD=<SMTP credentials password>
MAIL_FROM=TallyTime <no-reply@akashanil.dev>
TURNSTILE_SITE_KEY=<site key>
TURNSTILE_SECRET=<secret key>
CONTACT_EMAIL=privacy@akashanil.dev
```

`PUBLIC_URL` must start with `https://`, because that turns on secure cookies. The limits (5 checks a day, 5 minutes per document,
30 minutes per check, 2 hours in the queue) are already the defaults. Then:

```bash
sudo systemctl restart tallytime-web tallytime-worker
```

Check that email works (it shows the exact error if it does not):

```bash
cd /opt/tallytime && sudo -u tallytime .venv/bin/python -m app.admin test-email you@example.com
```

| Error | Meaning |
|---|---|
| `SMTPAuthenticationError` (535) | Wrong SMTP username or password: generate new SMTP credentials |
| `SMTPSenderRefused`, or "not an approved sender" | `MAIL_FROM` is not exactly an approved sender in this region |
| Timeout or connection refused | Wrong `SMTP_HOST` (region), or outbound port 587 blocked |
| Sent, but lands in spam | DKIM not yet Active, or SPF missing: check the email domain page |

## 4. Check it works

```bash
curl -s https://tallytime.akashanil.dev/healthz        # {"ok": true, ...}
journalctl -u tallytime-web -u tallytime-worker -f     # live logs
```

Then in a browser:
1. Sign up with your own email and confirm it from the email.
2. Run a demo, then upload a real document and watch the queue and progress.
3. Turn on notifications and close the tab. You should get a notification when the check finishes.
4. Invite a second email address into your workspace and accept it from a private window.

Set up a free uptime monitor (for example UptimeRobot) on `https://tallytime.akashanil.dev/healthz`. It returns 503 if the worker stops.

## 5. Everyday operation

| Task | Command |
|---|---|
| Update to the latest code | `cd /opt/tallytime && sudo -u tallytime git pull && sudo -u tallytime .local/bin/uv pip install --python .venv/bin/python -r requirements.txt && sudo systemctl restart tallytime-web tallytime-worker` |
| Usage at a glance | `cd /opt/tallytime && sudo -u tallytime .venv/bin/python -m app.admin stats` |
| List accounts | `… -m app.admin users` |
| Give a pilot exporter more checks | `… -m app.admin set-limit name@company.com 20` |
| Confirm an email by hand | `… -m app.admin verify name@company.com` |
| Delete an account and its data | `… -m app.admin delete-user name@company.com` |
| Restart | `sudo systemctl restart tallytime-web tallytime-worker` |
| Logs | `journalctl -u tallytime-worker --since "1 hour ago"` |

Restarting the worker during a check is safe: the check goes back to the front of the queue and starts again (documents already read come from the cache).

## 6. Backups and restore

Every night at 02:15, `deploy/backup.sh` writes `/var/backups/tallytime/accounts-YYYY-MM-DD.db` and keeps 7 days.
The copy holds accounts, workspaces and members only. Shipments, documents, results, sessions and push subscriptions are removed from it,
so backups never keep shipment data past the 7-day promise. To keep a copy off the VM, push the folder to Oracle Object Storage
(Always Free includes 20 GB) with `oci os object bulk-upload`, or `rsync` it to another machine.

To restore: stop both services, copy a backup over `/opt/tallytime/data/tally.db`, `chown tallytime:tallytime` it, and start them again.

## 7. Capacity

With one worker on 4 Ampere cores, a new document takes about a minute, so the server reads roughly **60 documents an hour** (about 10 shipments).
Demos and repeated documents come from the cache and take seconds. When more than 2 hours of work is waiting, new checks get a polite
"busy, try again later" (`BUSY_BACKLOG`). If that happens often, it's time to look for a GPU (see the README); the worker design stays the same.

## 8. Before you announce it

- [ ] Have a lawyer read `static/privacy.html` and `static/terms.html`. They are drafts written to India's DPDP Act 2023, not legal advice.
- [ ] Check the operator name ("Akash A, Kerala, India") and contact address in both pages.
- [ ] Sign-up, confirmation, reset and invitation emails arrive in the inbox (not spam).
- [ ] `https://tallytime.akashanil.dev/healthz` is monitored.
- [ ] You can SSH in with your key, and password login is off (`PasswordAuthentication no`, Ubuntu's default on Oracle).
