#!/usr/bin/env python3
"""Challenge Pace Manager for MyFundedPerps sandbox.

Reads an account's challenge rules (profit target, daily loss floor, maxpace_manager.py
drawdown, consistency) plus its live risk snapshot, and prints a trading plan:

  * How much profit is still needed to hit the target
  * How much daily loss room remains before the floor breaches                                                    * Suggested daily profit budget (remaining profit / days left)
  * Recommended max position size from account notional limits
  * Pace check: are you on track, ahead, or behind?

Sandbox only. Works with fp_test_* keys. Stdlib only.

Usage:                                                      FP_API_KEY=fp_test_... python pace_manager.py [--account-id <id>]
    FP_API_KEY=fp_test_... python pace_manager.py --plan --json                                                 """

from __future__ import annotations

import argparse                                         import json
import os
import sys
from datetime import datetime, timezone
from urllib import error, request

DEFAULT_BASE_URL = "https://sandbox.myfundedperpetuals.com"


class PaceError(Exception):
    pass


def _api_get(base_url: str, api_key: str, path: str, params: str = "") -> dict:
    url = f"{base_url}{path}{params}"
    req = request.Request(url, headers={"Authorization": f"Bearer {api_key}"})
    try:
        with request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except error.HTTPError as e:
        body = e.read().decode()
        raise PaceError(f"GET {path} -> HTTP {e.code}: {body}") from e


def list_accounts(base_url: str, api_key: str) -> list[dict]:
    return _api_get(base_url, api_key, "/v1/accounts").get("data", [])


def account_detail(base_url: str, api_key: str, account_id: str) -> dict:
    return _api_get(base_url, api_key, f"/v1/accounts/{account_id}").get("data", {})


def trading_policy(base_url: str, api_key: str, account_id: str) -> dict:
    return _api_get(
        base_url, api_key, f"/v1/accounts/{account_id}/trading-policy"
    ).get("data", {})


def list_positions(base_url: str, api_key: str, account_id: str) -> list[dict]:
    return _api_get(
        base_url, api_key, "/v1/positions", f"?account_id={account_id}"
    ).get("data", [])


def _rule(policy: dict, rule_id: str) -> dict | None:
    for r in policy.get("account_rules", []):
        if r.get("id") == rule_id:
            return r.get("parameters", {})
    return None


def build_plan(account: dict, policy: dict, positions: list[dict]) -> dict:
    risk = account.get("risk", {}) or {}
    limits = policy.get("limits", {}) or {}

    starting = account.get("starting_balance") or risk.get("equity") or 0
    equity = risk.get("equity", starting)
    unrealized = risk.get("unrealized_pnl", 0)

    daily_loss_pct = _rule(policy, "max-daily-loss").get("pct", 0)
    max_dd_pct = _rule(policy, "max-drawdown").get("pct", 0)
    profit_target_pct = _rule(policy, "profit-target").get("pct", 0)
    consistency_pct = _rule(policy, "consistency").get("pct", 0)

    daily_loss_room = risk.get("daily_loss_room", 0)
    max_dd_room = risk.get("max_drawdown_room", 0)
    remaining_profit = risk.get("remaining_profit", 0)

    # ---- Derived numbers ----
    daily_loss_budget_usd = starting * (daily_loss_pct / 100)
    max_drawdown_budget_usd = starting * (max_dd_pct / 100)
    profit_target_usd = starting * (profit_target_pct / 100)

    loss_used_today = max(0, daily_loss_budget_usd - daily_loss_room)
    pct_of_daily_budget_used = (
        (loss_used_today / daily_loss_budget_usd * 100) if daily_loss_budget_usd else 0
    )

    # How much of the profit target remains
    pct_of_target_remaining = (
        (remaining_profit / profit_target_usd * 100) if profit_target_usd else 0
    )

    # Suggested daily profit budget: split remaining profit across a default
    # 10-trading-day window (adjustable). Keeps you from grinding too fast or
    # leaving it to the last day.
    days_left = 10
    suggested_daily_profit = remaining_profit / days_left

    # Recommended max single position notional: cap at daily loss room so one
    # bad trade can't breach the floor, and respect account min notional.
    max_position_notional = min(daily_loss_room, limits.get("max_position_value_usd", float("inf")))
    min_notional = limits.get("min_order_notional_usd", 10)
    recommended_size_usd = max(min_notional, min(max_position_notional, 500))

    # Pace status
    if pct_of_target_remaining <= 0:
        pace = "target_reached"
    elif pct_of_daily_budget_used >= 80:
        pace = "loss_budget_nearly_spent"
    elif remaining_profit <= 0:
        pace = "target_met"
    else:
        pace = "on_track"

    return {
        "account_id": account.get("id"),
        "account_name": account.get("name"),
        "stage": account.get("stage"),
        "equity": round(equity, 2),
        "starting_balance": round(starting, 2),
        "unrealized_pnl": round(unrealized, 4),
        "rules": {
            "daily_loss_pct": daily_loss_pct,
            "max_drawdown_pct": max_dd_pct,
            "profit_target_pct": profit_target_pct,
            "consistency_pct": consistency_pct,
        },
        "budgets": {
            "daily_loss_budget_usd": round(daily_loss_budget_usd, 2),
            "loss_used_today_usd": round(loss_used_today, 2),
            "daily_loss_room_usd": round(daily_loss_room, 2),
            "max_drawdown_room_usd": round(max_dd_room, 2),
            "remaining_profit_usd": round(remaining_profit, 2),
            "profit_target_usd": round(profit_target_usd, 2),
        },
        "pace": {
            "pct_of_daily_budget_used": round(pct_of_daily_budget_used, 1),
            "pct_of_target_remaining": round(pct_of_target_remaining, 1),
            "suggested_daily_profit_usd": round(suggested_daily_profit, 2),
            "status": pace,
        },
        "sizing": {
            "recommended_max_position_usd": round(recommended_size_usd, 2),
            "min_order_notional_usd": min_notional,
            "max_open_positions": limits.get("max_open_positions"),
        },
        "open_positions": len(positions),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="MyFundedPerps challenge pace manager (sandbox)."
    )
    p.add_argument("--account-id", help="Account to manage (defaults to first sandbox account)")
    p.add_argument(
        "--base-url",
        default=os.environ.get("FP_BASE_URL", DEFAULT_BASE_URL),
        help="API host (default sandbox)",
    )
    p.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON plan",
    )
    args = p.parse_args(argv)

    api_key = os.environ.get("FP_API_KEY")
    if not api_key:
        print("error: set FP_API_KEY (your fp_test_ sandbox key)", file=sys.stderr)
        return 1

    # Resolve account.
    account_id = args.account_id
    if not account_id:
        accounts = list_accounts(args.base_url, api_key)
        if not accounts:
            print("error: no sandbox accounts found for this key", file=sys.stderr)
            return 1
        account_id = accounts[0]["id"]
        if not args.json:
            print(f"no --account-id given; using {account_id} ({accounts[0]['name']})")

    try:
        account = account_detail(args.base_url, api_key, account_id)
        policy = trading_policy(args.base_url, api_key, account_id)
        positions = list_positions(args.base_url, api_key, account_id)
    except PaceError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    plan = build_plan(account, policy, positions)

    if args.json:
        print(json.dumps(plan, indent=2))
        return 0

    b = plan["budgets"]
    pace = plan["pace"]
    sz = plan["sizing"]

    print(f"=== Challenge Pace: {plan['account_name']} ({plan['account_id']}) ===")
    print(f"Stage: {plan['stage']}  Equity: ${plan['equity']:.2f}  Unrealized: ${plan['unrealized_pnl']:.4f}")
    print()
    print("Challenge rules:")
    print(f"  Daily loss floor : {plan['rules']['daily_loss_pct']}%  "
          f"Max drawdown : {plan['rules']['max_drawdown_pct']}%  "
          f"Profit target : {plan['rules']['profit_target_pct']}%  "
          f"Consistency : {plan['rules']['consistency_pct']}%")
    print()
    print("Budgets today:")
    print(f"  Daily loss budget : ${b['daily_loss_budget_usd']:.2f}")
    print(f"  Loss used today   : ${b['loss_used_today_usd']:.2f}  ({pace['pct_of_daily_budget_used']}%)")
    print(f"  Daily loss room   : ${b['daily_loss_room_usd']:.2f}")
    print(f"  Max DD room       : ${b['max_drawdown_room_usd']:.2f}")
    print(f"  Remaining profit  : ${b['remaining_profit_usd']:.2f} / ${b['profit_target_usd']:.2f} target  ({pace['pct_of_target_remaining']}% left)")
    print()
    print("Pace:", pace["status"].replace("_", " ").title())
    print(f"  Suggested daily profit: ${pace['suggested_daily_profit_usd']:.2f} (over ~10 days)")
    print()
    print("Sizing:")
    print(f"  Recommended max position: ${sz['recommended_max_position_usd']:.2f}")
    print(f"  Min order notional      : ${sz['min_order_notional_usd']:.2f}")
    print(f"  Max open positions      : {sz['max_open_positions']}")
    print(f"  Open positions now      : {plan['open_positions']}")
    print()
    if pace["status"] == "loss_budget_nearly_spent":
        print("WARNING: You've used most of today's loss budget. Consider stopping.")
    elif pace["status"] == "target_reached":
        print("GOAL: Profit target reached.")
    print(f"Generated {plan['generated_at']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
