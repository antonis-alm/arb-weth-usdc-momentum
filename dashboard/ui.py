from __future__ import annotations

from decimal import Decimal
from typing import Any

import streamlit as st
from almanak.framework.dashboard.templates import (
    get_rsi_config,
    prepare_ta_session_state,
    render_ta_dashboard,
)


def _to_decimal(value: Any, default: str) -> Decimal:
    try:
        return Decimal(str(value))
    except Exception:
        return Decimal(default)


def _build_rsi_config(strategy_config: dict[str, Any]):
    rsi_period = int(strategy_config.get("rsi_period", 14))
    rsi_lower = float(strategy_config.get("rsi_lower", 40))
    rsi_upper = float(strategy_config.get("rsi_upper", 60))

    config = get_rsi_config(
        period=rsi_period,
        overbought=rsi_upper,
        oversold=rsi_lower,
    )
    config.signal_type = "momentum"
    config.base_token = str(strategy_config.get("base_token", config.base_token))
    config.quote_token = str(strategy_config.get("quote_token", config.quote_token))
    config.chain = str(strategy_config.get("chain", config.chain))
    config.protocol = str(strategy_config.get("protocol", config.protocol))
    return config


def _render_regime_metrics(strategy_config: dict[str, Any], session_state: dict[str, Any]) -> None:
    status = session_state.get("status", {})
    state = status.get("state", {}) if isinstance(status, dict) else {}

    prev_rsi = _to_decimal(state.get("prev_rsi"), "0")
    last_signal = str(state.get("last_signal", "none")).replace("_", " ").title()
    holding_asset = str(state.get("holding_asset", "quote")).upper()

    rsi_lower = _to_decimal(strategy_config.get("rsi_lower", 40), "40")
    rsi_upper = _to_decimal(strategy_config.get("rsi_upper", 60), "60")

    if prev_rsi > rsi_upper:
        momentum_regime = "Bullish momentum"
    elif prev_rsi < rsi_lower:
        momentum_regime = "Bearish momentum"
    else:
        momentum_regime = "Neutral range"

    if holding_asset in {"BASE", str(strategy_config.get("base_token", "WETH")).upper()}:
        position_regime = "Long base"
    else:
        position_regime = "Quote defensive"

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("RSI", f"{prev_rsi:.2f}")
    col2.metric("Momentum", momentum_regime)
    col3.metric("Position Regime", position_regime)
    col4.metric("Last Signal", last_signal)


def render_custom_dashboard(
    strategy_id: str,
    strategy_config: dict[str, Any],
    api_client: Any,
    session_state: dict[str, Any],
) -> None:
    st.title("Arb WETH/USDC Momentum")

    config = _build_rsi_config(strategy_config)

    session_state = prepare_ta_session_state(
        api_client,
        session_state=session_state,
        config=config,
    )

    _render_regime_metrics(strategy_config, session_state)
    render_ta_dashboard(strategy_id, strategy_config, session_state, config)
