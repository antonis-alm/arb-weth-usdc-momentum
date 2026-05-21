from unittest.mock import MagicMock, patch

from dashboard.ui import _build_rsi_config, render_custom_dashboard


def test_build_rsi_config_uses_momentum_thresholds():
    strategy_config = {
        "rsi_period": 14,
        "rsi_lower": 45,
        "rsi_upper": 55,
        "base_token": "WETH",
        "quote_token": "USDC",
        "chain": "arbitrum",
        "protocol": "uniswap_v3",
    }

    config = _build_rsi_config(strategy_config, session_state={})

    assert config.indicator_name == "RSI"
    assert config.indicator_period == 14
    assert config.lower_threshold == 45
    assert config.upper_threshold == 55
    assert config.signal_type == "momentum"
    assert config.base_token == "WETH"
    assert config.quote_token == "USDC"
    assert config.chain == "arbitrum"
    assert config.protocol == "uniswap_v3"


def test_build_rsi_config_prefers_runtime_state_bounds():
    strategy_config = {
        "rsi_period": 14,
        "rsi_lower": 45,
        "rsi_upper": 55,
    }
    session_state = {
        "status": {
            "state": {
                "rsi_lower": "40",
                "rsi_upper": "60",
            }
        }
    }

    config = _build_rsi_config(strategy_config, session_state=session_state)

    assert config.lower_threshold == 40
    assert config.upper_threshold == 60


@patch("dashboard.ui.render_ta_dashboard")
@patch("dashboard.ui.prepare_ta_session_state")
@patch("dashboard.ui.st.metric")
@patch("dashboard.ui.st.columns")
@patch("dashboard.ui.st.title")
def test_render_custom_dashboard_renders_template_and_regime_metrics(
    mock_title,
    mock_columns,
    mock_metric,
    mock_prepare,
    mock_render,
):
    strategy_config = {
        "rsi_period": 14,
        "rsi_lower": 45,
        "rsi_upper": 55,
        "base_token": "WETH",
        "quote_token": "USDC",
        "chain": "arbitrum",
        "protocol": "uniswap_v3",
    }
    session_state = {
        "status": {
            "state": {
                "prev_rsi": "58.1",
                "holding_asset": "base",
                "last_signal": "bull_cross",
            }
        }
    }

    mock_columns.return_value = [MagicMock(), MagicMock(), MagicMock(), MagicMock()]
    mock_prepare.return_value = session_state

    render_custom_dashboard(
        "arb_weth_usdc_momentum",
        strategy_config,
        api_client=MagicMock(),
        session_state=session_state,
    )

    mock_title.assert_called_once_with("Arb WETH/USDC Momentum")
    mock_prepare.assert_called_once()
    mock_render.assert_called_once()

    call_args = mock_render.call_args.args
    assert call_args[0] == "arb_weth_usdc_momentum"
    assert call_args[1] == strategy_config
    assert call_args[2] == session_state
    assert call_args[3].signal_type == "momentum"

    assert mock_columns.call_count == 1
    assert mock_metric.call_count == 0

    cols = mock_columns.return_value
    cols[0].metric.assert_called_once_with("RSI", "58.10")
    cols[1].metric.assert_called_once_with("Momentum", "Bullish momentum")
    cols[2].metric.assert_called_once_with("Position Regime", "Long base")
    cols[3].metric.assert_called_once_with("Last Signal", "Bull Cross")
