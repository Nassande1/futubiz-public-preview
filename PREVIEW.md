# Futubiz — small public practice preview

This is a separate copy of the local practice app. It is **not production infrastructure**. Balances, results, charts and trades are simulated in the browser. The read-only quote route is independent of the simulator. There are no user accounts, real trades, credentials or order endpoints. This app is not affiliated with Mile. Never add API keys, tokens, passwords, personal information or other secrets to this folder or its repository. All files under `public/` are publicly served.

**Before public release:** obtain explicit permission to use and redistribute any provider data, and verify that the upstream actually works from the chosen host. Neither permission nor live availability has been established. The endpoint may disappear, require permission/authentication, change format or return delayed/synthetic data. Quote failures leave the practice interface usable; do not represent prices as guaranteed, current or executable.

## Run and test locally

Requires Python 3.9+. Run `python3 server.py` and open `http://127.0.0.1:8000/`. Run `python3 -m unittest -v test_server test_limits`. Default bind is localhost; `--host` and `--port` override defaults. `PORT` supplies the default port (8000 if unset). No external Python packages or account credentials are needed.

## Render free preview configuration

`render.yaml` defines one free Python web service, compiles the script in the build, binds `0.0.0.0`, and reads Render's `PORT`. Render provides HTTPS. Free service availability, quotas, cold starts, sleep behavior and terms can change; verify current platform terms before deploying. The YAML does not create or deploy a service by itself. No repository or public service is created here.

The YAML opts into `TRUST_RENDER_PROXY=1`: client buckets use **only** the single valid `CF-Connecting-IP` header, rather than caller-supplied `X-Forwarded-For`. Missing, malformed or duplicated values share one fail-closed bucket. This option is safe only if every request reaches the app exclusively through an ingress that sets/overwrites that header, with no origin bypass. Render says its public services pass through Cloudflare, and Cloudflare documents this header, but **the actual header behavior for this service has not been tested**. Before public exposure, verify independently that separate clients are distinguished and that forged/multiple headers and direct-origin requests cannot bypass limits. If not, do not enable this proxy trust mode; without it the immediate peer is used, which can aggregate all visitors behind a proxy. Never set it on an internet-facing server reachable directly. References: https://render.com/articles/how-render-handles-ddos-attacks and https://developers.cloudflare.com/fundamentals/reference/http-headers/ .

## Guardrails and limitations

- GET and known write methods: 60 requests per IP per 60-second fixed window; quote requests: 30 per IP per window. Over limit returns 429. An in-memory table holds at most 2,048 active IPs; new IPs are rejected until an old window expires if full. Fixed windows can burst across boundaries; shared IPs share limits. Counters are per process, reset on restart and are not shared across multiple instances. The preview is intended for one instance only.
- At most 32 simultaneous accepted connections; excess connections are closed. Socket inactivity is limited to 10 seconds per operation. At most 3 concurrent upstream requests and 60 globally per 60-second fixed window; additional quote requests return 503 without an upstream call. Global limits can burst across window boundaries. These constraints limit damage but do **not** provide a strict end-to-end deadline, total bandwidth cap, complete slow-client protection, or DDoS protection. For wider traffic, use a production server, an edge/WAF, robust deadlines and shared distributed limits.
- `/api/quotes` is a fixed outbound URL `https://api.miletrades.site/api/v1/quotes`; it accepts no query parameters and does not follow redirects. No caller-supplied destination or credentials are accepted. Socket operations time out after 5 seconds, not a total deadline. Responses are limited to 512 KiB, 1,000 quotes, and validated fields; bad responses yield 502 and timeouts 504. The rate limiter also returns 429; global/upstream saturation returns 503. No cross-origin access is granted. Responses use `no-store`. There is no data freshness timestamp.
- The browser may also function without the quote service. Any historical/sample values shown in tests or documentation are examples only, not verified current quotes.

Provider documentation, subject to verification: https://milepredictions.com/developer/docs .
