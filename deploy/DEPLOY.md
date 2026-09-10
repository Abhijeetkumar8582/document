# Deploying to 15.207.14.33

One EC2 host runs everything: uvicorn serves the API **and** the built frontend on port 8000. The browser
talks to one origin, so no CORS or API-address configuration is needed for the app itself. Files go to S3;
the database is SQLite on the host under `backend/data/`.

## One-time setup

1. **Security group**: allow inbound TCP 8000 (and 22 for SSH) from where you'll use it.
2. **Clone and run the setup script** on the host:

   ```bash
   sudo apt-get install -y git
   git clone <your repo url> /opt/registrar
   cd /opt/registrar
   sudo bash deploy/setup.sh
   ```

   It installs Python and Node, creates the virtualenv, builds the frontend, and installs a systemd service
   named `registrar` that starts on boot.

3. **Create `backend/.env` on the server.** It is gitignored, so copy your local one or fill in the example:

   ```bash
   nano /opt/registrar/backend/.env
   ```

   Required lines:

   ```
   GEMINI_API_KEY=...
   STORAGE_BACKEND=s3
   S3_BUCKET=unifuse
   S3_REGION=us-east-1
   AWS_ACCESS_KEY_ID=...
   AWS_SECRET_ACCESS_KEY=...
   WORKER_CONCURRENCY=2
   ```

   Then `sudo systemctl restart registrar`.

4. **Bucket CORS** must list the origin the browser uses. `deploy/s3-cors.json` already includes
   `http://15.207.14.33` and `http://15.207.14.33:8000`. Apply it in S3 → unifuse → Permissions → CORS, or run
   `backend/.venv/bin/python scripts/check_s3.py` on the host to confirm.

5. Open **http://15.207.14.33:8000**.

## Each release

```bash
cd /opt/registrar && bash deploy/update.sh
```

## Useful commands

```bash
sudo systemctl status registrar        # is it running
sudo journalctl -u registrar -f        # live logs
sudo systemctl restart registrar       # after editing backend/.env
```

## Serving on port 80 or HTTPS later

Put nginx in front and proxy everything to `127.0.0.1:8000`. Because the API serves the frontend, a single
`location / { proxy_pass http://127.0.0.1:8000; }` block is enough. Add the new origin (`http://15.207.14.33`
or your domain) to `CORS_ORIGINS` in `backend/.env` and to the bucket's CORS rule.

## Running the frontend separately (optional)

If you ever host the frontend somewhere else (S3 website, Amplify, nginx on another port), tell it where the API
is before building: put `VITE_API_BASE=http://15.207.14.33:8000` in `frontend/.env`, run `npm run build`, and add
the frontend's origin to `CORS_ORIGINS` in `backend/.env` and to the bucket CORS rule.
