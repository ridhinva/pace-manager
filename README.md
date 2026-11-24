Pace-Manager
============

A challenge pace manager for MyFundedPerps sandbox accounts. Unlike a drawdown
guard (which only stops bleeding), this helps you **pace yourself to pass the
challenge**: it reads your account's profit target, daily loss floor, max
drawdown, and consistency rules, then computes a daily trading plan — how much
you can afford to lose today, how much profit remains, and a recommended
position size so one bad trade can't breach your floor.

## What it does

- Reads `GET /v1/accounts/{id}` for the risk snapshot (equity, unrealized P&L,
  daily loss room, max drawdown room, remaining profit).
- Reads `GET /v1/accounts/{id}/trading-policy` for the challenge rules
  (daily loss %, max drawdown %, profit target %, consistency %).
- Computes:
  - Daily loss budget vs. how much you've already used today
  - Remaining profit to hit the target, as a %
  - Suggested daily profit budget (spread across ~10 trading days)
  - Recommended max position size so a single loss can't breach the floor
- Prints a pace status: on track, loss budget nearly spent, or target reached.
- `--json` emits a machine-readable plan for dashboards or bots.

## Prerequisites

- Python 3.8+ (stdlib only — no external dependencies)
- A MyFundedPerps sandbox API key starting with `fp_test_` (create one at
  https://myfundedperpetuals.com/settings?section=api-keys under Test
  environment)

## Install & run

```bash
export FP_API_KEY=fp_test_...your-sandbox-key...
python pace_manager.py --account-id <your-sandbox-account-id>
```

Omit `--account-id` to manage the first sandbox account returned by your key.

Machine-readable output:
```bash
python pace_manager.py --json
```

## Exit codes

- `0` — plan printed successfully
- `1` — error

## Safety

- Sandbox only. This key will not work on the live host, and the manager is
  read-only — it never places or closes orders.
- Never commit `FP_API_KEY` to git. Add it to your shell env or a local
  `.env` you keep out of version control.

## Built on

MyFundedPerps REST API v1 (sandbox host `sandbox.myfundedperpetuals.com`):
- `GET /v1/accounts` — list accounts
- `GET /v1/accounts/{id}` — account + risk snapshot
- `GET /v1/accounts/{id}/trading-policy` — challenge rules + limits
- `GET /v1/positions?account_id=` — open positions

Docs: https://docs.myfundedperpetuals.com/quickstart
