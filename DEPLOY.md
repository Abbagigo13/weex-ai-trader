# Deployment Guide

How to take this project from a local Windows machine (where WEEX
blocks the residential IP) to a Linux VPS (where it will work).

Estimated setup time: 30–45 minutes.

---

## Prerequisites

- A VPS with a **static IPv4 address**
  - Recommended: Ubuntu 22.04 LTS, 2 vCPU, 2 GB RAM
  - Providers: Hetzner, DigitalOcean, Linode, Vultr, AWS Lightsail
  - Location matters less than IP reputation — pick a *residential*-friendly region
- SSH access to the VPS
- A WEEX account with 2FA enabled
- A WEEX API key (created on the VPS, not locally)

---

## Step 1 — Prepare the VPS

SSH in:

```bash
ssh root@YOUR_VPS_IP

Update and install Python + git:

bash
apt update && apt upgrade -y
apt install -y python3 python3-venv python3-pip git curl ufw
Open only what you need:

bash
ufw allow 22/tcp          # SSH
ufw allow 8000/tcp        # backend API
ufw allow 5173/tcp        # frontend dev server (temporary)
ufw --force enable

Step 2 — Verify WEEX connectivity from the VPS
This is the most important step. Before deploying anything,
confirm the VPS can reach WEEX:

bash
curl -s "https://api-contract.weex.com/capi/v3/market/ticker/24hr?symbol=BTCUSDT" | head -c 400
If you see JSON like:

text
[{"symbol":"BTCUSDT","priceChange":"...","lastPrice":"...",...}]
…then WEEX is reachable, and the whole TLS problem is gone.

If you see Recv failure: Connection was reset, the VPS IP is
also blocked. Try a different VPS provider or use a residential
proxy. Do not proceed until this returns JSON.

tep 3 — Clone or upload the project
Option A — from a git repo:

bash
git clone <your_repo_url> /opt/weex-ai-trader
cd /opt/weex-ai-trader
Option B — upload via scp from Windows (in PowerShell):

powershell
scp -r C:\Users\PC\weex-ai-trader root@YOUR_VPS_IP:/opt/weex-ai-trader
Then on the VPS:

bash
cd /opt/weex-ai-trader

Step 4 — Backend setup
bash
cd /opt/weex-ai-trader/backend

# Virtual env
python3 -m venv .venv
source .venv/bin/activate

# Dependencies
pip install --upgrade pip
pip install -r requirements.txt
If requirements.txt does not include these, add them:

text
fastapi
uvicorn[standard]
httpx
python-dotenv

Install:

bash
pip install fastapi "uvicorn[standard]" httpx python-dotenv
Step 5 — Fix the transport
On Linux, the curl.exe transport from weex.py will not work.
We swap it for a native HTTP client that runs on the VPS.

Step 5 — Fix the transport
On Linux, the curl.exe transport from weex.py will not work.
We swap it for a native HTTP client that runs on the VPS.

Edit backend/app/services/weex.py.

Replace the entire _curl_get_json method with this native version:
    def _curl_get_json(
        self, path: str, params: Dict[str, Any]
    ) -> Any:
        import httpx

        url = f"{self.base_url}{path}"

        weight = self._weight_for(path)
        max_attempts = 4
        last_error = ""

        for attempt in range(1, max_attempts + 1):
            self.limiter.acquire(cost=weight, blocking=True)

            try:
                r = httpx.get(
                    url,
                    params=params,
                    timeout=20.0,
                    headers={"Accept": "application/json"},
                )
            except httpx.HTTPError as exc:
                last_error = str(exc)
                self.limiter.apply_transport_cooldown(1.0 * attempt)
                continue

            # Record rate-limit headers
            remaining = r.headers.get("X-REMAINING-WEIGHT-10S")
            self.limiter.observe_response(
                remaining_weight=(
                    int(remaining) if remaining is not None else None
                ),
                status_code=r.status_code,
            )

            if r.status_code == 200:
                try:
                    return r.json()
                except ValueError as exc:
                    raise WEEXClientError(
                        f"Invalid JSON from {url}: {r.text[:200]}"
                    ) from exc

            if r.status_code == 429:
                time.sleep(2.0 * attempt)
                last_error = "429 rate limited"
                continue

            if 500 <= r.status_code < 600:
                time.sleep(1.0 * attempt)
                last_error = f"HTTP {r.status_code}"
                continue

            raise WEEXClientError(
                f"HTTP {r.status_code} from {url}: {r.text[:200]}"
            )

        raise WEEXClientError(
            f"Failed after {max_attempts} attempts for {url}: {last_error}"
        )

        Then remove the shutil import and the _curl_path check in __init__:

python
    def __init__(self):
        self.base_url = "https://api-contract.weex.com/capi/v3"
        self.limiter = RateLimiter(
            budget=500, window_seconds=10.0, safety_margin=50,
        )
Everything else stays the same — get_ticker, get_candles,
rate limiter, logging, error handling.

Verify the transport swap:
python -c "
import asyncio
from app.services.weex import WEEXClient
async def main():
    c = WEEXClient()
    t = await c.get_ticker('cmt_btcusdt')
    print('last:', t['last'])
asyncio.run(main())
"

Step 6 — Configure .env
Create backend/.env:

bash
cat > /opt/weex-ai-trader/backend/.env << 'EOF'
ENVIRONMENT=production
TRADING_ENABLED=false
PAPER_TRADING=true
API_PREFIX=/api
APP_NAME=Abbigigo AI Trader
EOF
Do not add WEEX API keys yet. That comes in Step 8.

Step 7 — Run the backend as a service
Create /etc/systemd/system/weex-trader.service:
cat > /etc/systemd/system/weex-trader.service << 'EOF'
[Unit]
Description=WEEX AI Trader Backend
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/weex-ai-trader/backend
Environment="PATH=/opt/weex-ai-trader/backend/.venv/bin"
ExecStart=/opt/weex-ai-trader/backend/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable weex-trader
systemctl start weex-trader
systemctl status weex-trader

Check it works:

bash
curl -s http://127.0.0.1:8000/api/health
Should return {"status":"ok"}.

Check the log file:

bash
tail -f /opt/weex-ai-trader/backend/logs/trader.log
You should see:

text
[...] | INFO    | [SYSTEM   ] Backend starting app=... env=production
Step 8 — Create the WEEX API key

Log into WEEX from a browser.

Go to https://www.weex.com/account/newapi.

Create a dedicated key for AI Wars II.

Bind the key to the VPS static IP.

Enable trading permissions.

Save the API key, secret, passphrase.

Add them to backend/.env:

bash
cat >> /opt/weex-ai-trader/backend/.env << 'EOF'
WEEX_API_KEY=your_key_here
WEEX_API_SECRET=your_secret_here
WEEX_API_PASSPHRASE=your_passphrase_here
EOF

chmod 600 /opt/weex-ai-trader/backend/.env
Restart the backend:

bash
systemctl restart weex-trader
Never copy these keys to your Windows machine, Slack, GitHub,
or anywhere else. The .env stays on the VPS.

Step 9 — Verify the full pipeline
From the VPS:
curl -s "http://127.0.0.1:8000/api/market/cmt_btcusdt" | head -c 400
curl -s "http://127.0.0.1:8000/api/candles/cmt_btcusdt?limit=5" | head -c 400
curl -s "http://127.0.0.1:8000/api/analyze/cmt_btcusdt" | head -c 400
curl -s -X POST "http://127.0.0.1:8000/api/paper/auto?symbol=cmt_btcusdt" | head -c 400
curl -s "http://127.0.0.1:8000/api/paper/state"
Every one should return JSON, no 500s, no Connection was reset.

Step 10 — Frontend (optional)
The dashboard is optional for competition scoring. If you want it
running on the VPS:
cd /opt/weex-ai-trader/frontend
apt install -y nodejs npm
npm install
npm run build
Serve dist/ with nginx:

apt install -y nginx

cat > /etc/nginx/sites-available/weex-trader << 'EOF'
server {
    listen 80;
    server_name YOUR_VPS_IP;

    root /opt/weex-ai-trader/frontend/dist;
    index index.html;

    location / {
        try_files $uri /index.html;
    }

    location /api/ {
        proxy_pass http://127.0.0.1:8000/api/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
EOF

ln -sf /etc/nginx/sites-available/weex-trader /etc/nginx/sites-enabled/
nginx -t
systemctl restart nginx

Update frontend/src/App.jsx:

javascript
const API = "/api";
Then rebuild: npm run build.

Step 11 — Post-deploy checks
Check Command Expected
Backend up systemctl status weex-trader active (running)
Health curl 127.0.0.1:8000/api/health {"status":"ok"}
Market data curl 127.0.0.1:8000/api/market/cmt_btcusdt live ticker
Auto cycle curl -X POST 127.0.0.1:8000/api/paper/auto JSON with mode ENTRY_SCAN
Kill switch curl 127.0.0.1:8000/api/kill/status {"active": false}
Rate limiter curl 127.0.0.1:8000/api/rate-limiter/status budget 500
Log file tail logs/trader.log [MARKET] lines with real data
Step 12 — Only then, enable live trading
Do not do this until Steps 1–11 are fully green for at least 24 hours of paper trading.

Confirm the paper engine has opened and closed positions cleanly.

Confirm SQLite is persisting trades across restarts.

Confirm the kill switch blocks new positions.

Confirm the rate limiter never trips 429 more than twice in a row.

Then — and only then — wire the authenticated order endpoint
into trading_service.execute_order().

Keep the kill switch wired to a physical or remote trigger you can
hit at any time.

### Troubleshooting
Symptom Likely cause Fix
Connection was reset from VPS VPS IP also flagged Change provider or use proxy
429 Too Many Requests Rate limit hit Lower safety_margin; add sleep
Backend crashes on start .env malformed Check journalctl -u weex-trader -n 50
paper_trading.db locked Two processes writing Ensure only one uvicorn runs
Time skew errors from WEEX VPS clock drift apt install chrony
Security Notes
.env file: chmod 600

Firewall: only expose 22, 80, 443, 8000 as needed

Never log secrets — the sanitizer already handles this

Rotate the API key if it ever appears in a screenshot or log

Bind the key to the VPS IP only
Rolling Back
bash
systemctl stop weex-trader
git checkout <previous_commit>
systemctl start weex-trader
The SQLite database at backend/data/paper_trading.db is not
affected by code rollbacks.

### Summary
Once the VPS is up:

curl WEEX ticker → JSON ✅

Backend service running ✅

All API endpoints responding ✅

.env has the API key ✅

Paper trading for 24 hours ✅
Then wire live execution

Only Step 12 touches live money. Everything before that is safe.
