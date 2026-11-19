from __future__ import annotations

from agent_run.errors import HitlError
from agent_run.openrouter import OpenRouterClient
from agent_run.state import RunState, StateStore


def refresh_spent(client: OpenRouterClient, state: RunState, store: StateStore) -> float:
    usage = client.get_usage_usd()
    state.spent_usd = max(0.0, usage - state.usage_baseline_usd)
    store.save(state)
    return state.spent_usd


def ensure_budget(client: OpenRouterClient, state: RunState, store: StateStore) -> None:
    spent = refresh_spent(client, state, store)
    if spent >= state.budget_usd:
        raise HitlError(
            "budget_exceeded",
            f"spent=${spent:.4f} >= budget=${state.budget_usd:.4f}",
        )
