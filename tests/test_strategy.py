from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import MagicMock

import pandas as pd

from strategy import ArbWethUsdcMomentumStrategy


def _make_market(
    *,
    candle_ts: datetime,
    rsi_value: str,
    base_balance: str,
    base_balance_usd: str,
    quote_balance_usd: str,
    price: str = "2000",
):
    market = MagicMock()

    candles = pd.DataFrame(
        [
            {
                "timestamp": candle_ts,
                "open": 1,
                "high": 1,
                "low": 1,
                "close": 1,
                "volume": 1,
            }
        ]
    )
    market.ohlcv.return_value = candles

    rsi = MagicMock()
    rsi.value = Decimal(rsi_value)
    market.rsi.return_value = rsi

    base = MagicMock()
    base.balance = Decimal(base_balance)
    base.balance_usd = Decimal(base_balance_usd)

    quote = MagicMock()
    quote.balance = Decimal(quote_balance_usd)
    quote.balance_usd = Decimal(quote_balance_usd)

    def _balance(token):
        return base if token == "WETH" else quote

    market.balance.side_effect = _balance
    market.price.return_value = Decimal(price)
    market.chain = "arbitrum"
    return market


def _strategy(config_overrides=None):
    config = {
        "chain": "arbitrum",
        "protocol": "uniswap_v3",
        "base_token": "WETH",
        "quote_token": "USDC",
        "pool_fee_tier": 500,
        "pool_address": "0xc6962004f452be9203591991d15f6b388e09e8d0",
        "timeframe": "5m",
        "rsi_period": 14,
        "rsi_lower": 45,
        "rsi_upper": 55,
        "trade_size_usd": 1000,
        "max_slippage_bps": 50,
        "min_base_balance": "0.0001",
        "force_action": "",
    }
    if config_overrides:
        config.update(config_overrides)

    return ArbWethUsdcMomentumStrategy(
        config=config,
        chain="arbitrum",
        wallet_address="0x" + "1" * 40,
    )


def test_initial_warmup_sets_baseline_and_holds():
    strategy = _strategy()
    market = _make_market(
        candle_ts=datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
        rsi_value="60",
        base_balance="0",
        base_balance_usd="0",
        quote_balance_usd="10000",
    )

    intent = strategy.decide(market)

    assert intent.intent_type.value == "HOLD"
    assert strategy._prev_rsi == Decimal("60")


def test_same_candle_is_processed_once_only():
    strategy = _strategy()
    ts = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    market = _make_market(
        candle_ts=ts,
        rsi_value="50",
        base_balance="0",
        base_balance_usd="0",
        quote_balance_usd="10000",
    )

    first = strategy.decide(market)
    second = strategy.decide(market)

    assert first.intent_type.value == "HOLD"
    assert second.intent_type.value == "HOLD"
    assert "Awaiting next confirmed 5m candle close" in second.reason


def test_cross_above_55_buys_weth():
    strategy = _strategy()

    first_market = _make_market(
        candle_ts=datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
        rsi_value="54",
        base_balance="0",
        base_balance_usd="0",
        quote_balance_usd="10000",
    )
    strategy.decide(first_market)

    second_market = _make_market(
        candle_ts=datetime(2026, 1, 1, 12, 5, tzinfo=UTC),
        rsi_value="56",
        base_balance="0",
        base_balance_usd="0",
        quote_balance_usd="10000",
    )
    intent = strategy.decide(second_market)

    assert intent.intent_type.value == "SWAP"
    assert intent.from_token == "USDC"
    assert intent.to_token == "WETH"


def test_cross_below_45_sells_weth():
    strategy = _strategy()

    first_market = _make_market(
        candle_ts=datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
        rsi_value="46",
        base_balance="1",
        base_balance_usd="2000",
        quote_balance_usd="1000",
    )
    strategy.decide(first_market)

    second_market = _make_market(
        candle_ts=datetime(2026, 1, 1, 12, 5, tzinfo=UTC),
        rsi_value="44",
        base_balance="1",
        base_balance_usd="2000",
        quote_balance_usd="1000",
    )
    intent = strategy.decide(second_market)

    assert intent.intent_type.value == "SWAP"
    assert intent.from_token == "WETH"
    assert intent.to_token == "USDC"


def test_cross_to_neutral_exits_base_position():
    strategy = _strategy()

    first_market = _make_market(
        candle_ts=datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
        rsi_value="62",
        base_balance="1",
        base_balance_usd="2000",
        quote_balance_usd="1000",
    )
    strategy.decide(first_market)

    second_market = _make_market(
        candle_ts=datetime(2026, 1, 1, 12, 5, tzinfo=UTC),
        rsi_value="54",
        base_balance="1",
        base_balance_usd="2000",
        quote_balance_usd="1000",
    )
    intent = strategy.decide(second_market)

    assert intent.intent_type.value == "SWAP"
    assert intent.from_token == "WETH"
    assert intent.to_token == "USDC"
    assert intent.amount == "all"


def test_neutral_cross_holds_if_already_in_usdc():
    strategy = _strategy()

    strategy._prev_rsi = Decimal("62")
    market = _make_market(
        candle_ts=datetime(2026, 1, 1, 12, 5, tzinfo=UTC),
        rsi_value="54",
        base_balance="0",
        base_balance_usd="0",
        quote_balance_usd="10000",
    )

    intent = strategy.decide(market)

    assert intent.intent_type.value == "HOLD"
    assert "Neutral cross but already holding USDC" in intent.reason


def test_no_duplicate_buy_when_already_holding_weth():
    strategy = _strategy()

    strategy._prev_rsi = Decimal("54")
    market = _make_market(
        candle_ts=datetime(2026, 1, 1, 12, 5, tzinfo=UTC),
        rsi_value="56",
        base_balance="1",
        base_balance_usd="2000",
        quote_balance_usd="10000",
    )

    intent = strategy.decide(market)

    assert intent.intent_type.value == "HOLD"
    assert "already holding WETH" in intent.reason


def test_no_duplicate_sell_when_already_holding_usdc():
    strategy = _strategy()

    strategy._prev_rsi = Decimal("46")
    market = _make_market(
        candle_ts=datetime(2026, 1, 1, 12, 5, tzinfo=UTC),
        rsi_value="44",
        base_balance="0",
        base_balance_usd="0",
        quote_balance_usd="10000",
    )

    intent = strategy.decide(market)

    assert intent.intent_type.value == "HOLD"
    assert "already holding USDC" in intent.reason


def test_non_cross_above_band_holds():
    strategy = _strategy()
    strategy._prev_rsi = Decimal("56")
    market = _make_market(
        candle_ts=datetime(2026, 1, 1, 12, 5, tzinfo=UTC),
        rsi_value="57",
        base_balance="0",
        base_balance_usd="0",
        quote_balance_usd="10000",
    )

    intent = strategy.decide(market)

    assert intent.intent_type.value == "HOLD"
    assert "No RSI crossing event" in intent.reason


def test_force_action_buy_bypasses_signal_gates():
    strategy = _strategy({"force_action": "buy"})
    market = _make_market(
        candle_ts=datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
        rsi_value="50",
        base_balance="0",
        base_balance_usd="0",
        quote_balance_usd="0",
    )

    intent = strategy.decide(market)

    assert intent.intent_type.value == "SWAP"
    assert intent.from_token == "USDC"
    assert intent.to_token == "WETH"


def test_force_action_sell_bypasses_signal_gates():
    strategy = _strategy({"force_action": "sell"})
    market = _make_market(
        candle_ts=datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
        rsi_value="50",
        base_balance="0",
        base_balance_usd="0",
        quote_balance_usd="0",
    )

    intent = strategy.decide(market)

    assert intent.intent_type.value == "SWAP"
    assert intent.from_token == "WETH"
    assert intent.to_token == "USDC"
    assert intent.amount == "all"


def test_persistent_state_roundtrip_preserves_cross_tracking():
    strategy = _strategy()
    strategy._prev_rsi = Decimal("51")
    strategy._last_processed_candle_ts = "2026-01-01T12:00:00+00:00"
    strategy._holding_asset = "base"
    strategy._last_signal = "bull_cross"

    saved = strategy.get_persistent_state()
    restored = _strategy()
    restored.load_persistent_state(saved)

    assert restored._prev_rsi == Decimal("51")
    assert restored._last_processed_candle_ts == "2026-01-01T12:00:00+00:00"
    assert restored._holding_asset == "base"
    assert restored._last_signal == "bull_cross"


def test_teardown_methods_work():
    strategy = _strategy()

    market = MagicMock()
    base = MagicMock()
    base.balance = Decimal("0.2")
    base.balance_usd = Decimal("400")
    market.balance.return_value = base

    strategy.create_market_snapshot = MagicMock(return_value=market)

    summary = strategy.get_open_positions()
    intents = strategy.generate_teardown_intents()

    assert len(summary.positions) == 1
    assert summary.positions[0].position_type.value == "TOKEN"
    assert len(intents) == 1
    assert intents[0].intent_type.value == "SWAP"
    assert intents[0].from_token == "WETH"
    assert intents[0].to_token == "USDC"
