from __future__ import annotations

from decimal import Decimal
from typing import Any

import streamlit as st
from almanak.framework.dashboard.templates import (
    get_rsi_config,
    prepare_ta_session_state,
    render_ta_dashboard,
)


def _as_decimal(value: Any, default: str) -> Decimal:
    try:
        return Decimal(str(value))
    except Exception:
        return Decimal(default)


def _runtime_state(session_state: dict[str, Any]) -> dict[str, Any]:
    status = session_state.get("status", {}) if isinstance(session_state, dict) else {}
    return status.get("state", {}) if isinstance(status, dict) else {}


def _resolve_rsi_bounds(
    strategy_config: dict[str, Any],
    session_state: dict[str, Any],
) -> tuple[Decimal, Decimal]:
    state = _runtime_state(session_state)

    lower = state.get("rsi_lower")
    if lower is None:
        lower = strategy_config.get("rsi_lower", strategy_config.get("rsi_oversold", 40))

    upper = state.get("rsi_upper")
    if upper is None:
        upper = strategy_config.get("rsi_upper", strategy_config.get("rsi_overbought", 60))

    return _as_decimal(lower, "40"), _as_decimal(upper, "60")


def _build_rsi_config(strategy_config: dict[str, Any], session_state: dict[str, Any]):
    rsi_period = int(strategy_config.get("rsi_period", 14))
    rsi_lower, rsi_upper = _resolve_rsi_bounds(strategy_config, session_state)

    config = get_rsi_config(
        period=rsi_period,
        oversold=float(rsi_lower),
        overbought=float(rsi_upper),
    )
    config.signal_type = "momentum"
    config.base_token = str(strategy_config.get("base_token", config.base_token))
    config.quote_token = str(strategy_config.get("quote_token", config.quote_token))
    config.chain = str(strategy_config.get("chain", config.chain))
    config.protocol = str(strategy_config.get("protocol", config.protocol))
    return config


def _regime_labels(
    strategy_config: dict[str, Any],
    session_state: dict[str, Any],
) -> tuple[str, str, str, Decimal]:
    state = _runtime_state(session_state)

    rsi_value = _as_decimal(state.get("prev_rsi"), "0")
    last_signal = str(state.get("last_signal", "none")).replace("_", " ").title()

    base_token = str(strategy_config.get("base_token", "WETH")).upper()
    holding_asset = str(state.get("holding_asset", "quote")).upper()
    position_regime = "Long base" if holding_asset in {"BASE", base_token} else "Quote defensive"

    rsi_lower, rsi_upper = _resolve_rsi_bounds(strategy_config, session_state)
    if rsi_value > rsi_upper:
        momentum = "Bullish momentum"
    elif rsi_value < rsi_lower:
        momentum = "Bearish momentum"
    else:
        momentum = "Neutral range"

    return momentum, position_regime, last_signal, rsi_value


def _render_overview_metrics(strategy_config: dict[str, Any], session_state: dict[str, Any]) -> None:
    momentum, position_regime, last_signal, rsi_value = _regime_labels(strategy_config, session_state)

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("RSI", f"{rsi_value:.2f}")
    col2.metric("Momentum", momentum)
    col3.metric("Position Regime", position_regime)
    col4.metric("Last Signal", last_signal)


def render_custom_dashboard(
    strategy_id: str,
    strategy_config: dict[str, Any],
    api_client: Any,
    session_state: dict[str, Any],
) -> None:
    st.title("Arb WETH/USDC Momentum")

    config = _build_rsi_config(strategy_config, session_state)
    hydrated_session_state = prepare_ta_session_state(
        api_client,
        session_state=session_state,
        config=config,
    )

    _render_overview_metrics(strategy_config, hydrated_session_state)
    render_ta_dashboard(strategy_id, strategy_config, hydrated_session_state, config)
