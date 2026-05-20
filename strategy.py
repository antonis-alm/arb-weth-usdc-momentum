import logging
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from almanak.framework.intents import Intent
from almanak.framework.market import MarketSnapshot, MarketSnapshotError
from almanak.framework.strategies import IntentStrategy, almanak_strategy

logger = logging.getLogger(__name__)


def _safe(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, Enum):
        return getattr(value, "value", str(value))
    return value


@almanak_strategy(
    name="arb_weth_usdc_momentum",
    description="RSI(14) 5m momentum crossing strategy for WETH/USDC on Arbitrum Uniswap V3",
    version="1.0.0",
    author="Generated",
    tags=["generated", "ta_swap", "momentum", "uniswap_v3"],
    supported_chains=["arbitrum"],
    supported_protocols=["uniswap_v3"],
    intent_types=["SWAP", "HOLD"],
    default_chain="arbitrum",
)
class ArbWethUsdcMomentumStrategy(IntentStrategy):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.protocol = str(self.get_config("protocol", "uniswap_v3"))
        self.base_token = str(self.get_config("base_token", "WETH"))
        self.quote_token = str(self.get_config("quote_token", "USDC"))
        self.pool_fee_tier = int(self.get_config("pool_fee_tier", 500))
        self.pool_address = str(self.get_config("pool_address", ""))
        self.timeframe = str(self.get_config("timeframe", "5m"))
        self.rsi_period = int(self.get_config("rsi_period", 14))
        self.rsi_lower = Decimal(str(self.get_config("rsi_lower", "45")))
        self.rsi_upper = Decimal(str(self.get_config("rsi_upper", "55")))
        self.trade_size_usd = Decimal(str(self.get_config("trade_size_usd", "1000")))
        self.max_slippage_bps = int(self.get_config("max_slippage_bps", 50))
        self.min_base_balance = Decimal(str(self.get_config("min_base_balance", "0.0001")))
        self.force_action = str(self.get_config("force_action", "") or "").lower()

        self._prev_rsi: Decimal | None = None
        self._last_processed_candle_ts: str | None = None
        self._holding_asset = "quote"
        self._last_signal = "none"

    def decide(self, market: MarketSnapshot) -> Intent:
        if self.force_action:
            return self._forced_intent(market)

        candle_ts = self._latest_confirmed_candle_ts(market)
        if candle_ts is None:
            return Intent.hold(reason="Confirmed 5m candle unavailable")

        if self._last_processed_candle_ts == candle_ts:
            return Intent.hold(reason="Awaiting next confirmed 5m candle close")

        self._last_processed_candle_ts = candle_ts

        try:
            rsi = market.rsi(self.base_token, period=self.rsi_period, timeframe=self.timeframe)
        except (ValueError, MarketSnapshotError) as exc:
            return Intent.hold(reason=f"RSI unavailable: {exc}")

        current_rsi = Decimal(str(rsi.value))
        previous_rsi = self._prev_rsi
        logger.info("RSI snapshot prev=%s latest=%s", previous_rsi, current_rsi)

        try:
            base_balance = market.balance(self.base_token)
            quote_balance = market.balance(self.quote_token)
        except (ValueError, MarketSnapshotError) as exc:
            return Intent.hold(reason=f"Balance unavailable: {exc}")

        self._holding_asset = "base" if base_balance.balance >= self.min_base_balance else "quote"

        if previous_rsi is None:
            self._prev_rsi = current_rsi
            self._last_signal = "none"
            return Intent.hold(reason="Initialized RSI baseline; waiting for crossing event")

        crossed_up = previous_rsi <= self.rsi_upper and current_rsi > self.rsi_upper
        crossed_down = previous_rsi >= self.rsi_lower and current_rsi < self.rsi_lower

        self._prev_rsi = current_rsi

        if crossed_up:
            self._last_signal = "bull_cross"
            if self._holding_asset == "base":
                return Intent.hold(reason="Bullish cross but already holding WETH")
            if quote_balance.balance_usd < self.trade_size_usd:
                return Intent.hold(reason="Bullish cross but insufficient USDC balance")
            return Intent.swap(
                from_token=self.quote_token,
                to_token=self.base_token,
                amount_usd=self.trade_size_usd,
                max_slippage=self._max_slippage(),
                protocol=self.protocol,
                chain=self.chain,
            )

        if crossed_down:
            self._last_signal = "bear_cross"
            if self._holding_asset == "quote":
                return Intent.hold(reason="Bearish cross but already holding USDC")
            try:
                base_price = market.price(self.base_token)
            except (ValueError, MarketSnapshotError) as exc:
                return Intent.hold(reason=f"Price unavailable: {exc}")

            if base_price <= 0:
                return Intent.hold(reason="Invalid WETH price")

            min_base_for_trade = self.trade_size_usd / base_price
            if base_balance.balance < min_base_for_trade:
                return Intent.hold(reason="Bearish cross but insufficient WETH balance")
            return Intent.swap(
                from_token=self.base_token,
                to_token=self.quote_token,
                amount_usd=self.trade_size_usd,
                max_slippage=self._max_slippage(),
                protocol=self.protocol,
                chain=self.chain,
            )

        self._last_signal = "none"
        return Intent.hold(reason=f"No RSI crossing event ({current_rsi})")

    def _forced_intent(self, market: MarketSnapshot) -> Intent:
        if self.force_action == "buy":
            return Intent.swap(
                from_token=self.quote_token,
                to_token=self.base_token,
                amount_usd=self.trade_size_usd,
                max_slippage=self._max_slippage(),
                protocol=self.protocol,
                chain=self.chain,
            )
        if self.force_action == "sell":
            return Intent.swap(
                from_token=self.base_token,
                to_token=self.quote_token,
                amount="all",
                max_slippage=self._max_slippage(),
                protocol=self.protocol,
                chain=self.chain,
            )
        raise ValueError(f"Unknown force_action: {self.force_action!r}")

    def _latest_confirmed_candle_ts(self, market: MarketSnapshot) -> str | None:
        pair = f"{self.base_token}/{self.quote_token}"
        try:
            candles = market.ohlcv(
                token=pair,
                timeframe=self.timeframe,
                limit=2,
                pool_address=self.pool_address or None,
            )
        except (ValueError, MarketSnapshotError):
            return None

        if candles is None or getattr(candles, "empty", True):
            return None

        latest = candles.iloc[-1]
        timestamp = latest.get("timestamp")
        if timestamp is None:
            return None

        if hasattr(timestamp, "to_pydatetime"):
            timestamp = timestamp.to_pydatetime()

        if isinstance(timestamp, datetime):
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=UTC)
            return timestamp.astimezone(UTC).isoformat()

        return str(timestamp)

    def _max_slippage(self) -> Decimal:
        return Decimal(str(self.max_slippage_bps)) / Decimal("10000")

    def get_status(self) -> dict[str, Any]:
        return {
            "strategy": "arb_weth_usdc_momentum",
            "chain": self.chain,
            "wallet": self.wallet_address[:10] + "..." if self.wallet_address else None,
            "state": {
                "holding_asset": self._holding_asset,
                "last_signal": self._last_signal,
                "prev_rsi": _safe(self._prev_rsi),
                "last_processed_candle_ts": _safe(self._last_processed_candle_ts),
            },
            "config": {
                "base_token": self.base_token,
                "quote_token": self.quote_token,
                "timeframe": self.timeframe,
                "rsi_period": self.rsi_period,
                "rsi_lower": str(self.rsi_lower),
                "rsi_upper": str(self.rsi_upper),
                "trade_size_usd": str(self.trade_size_usd),
            },
        }

    def on_intent_executed(self, intent, success: bool, result):
        if not success:
            return
        intent_type = getattr(intent, "intent_type", None)
        if not intent_type or intent_type.value != "SWAP":
            return

        from_token = getattr(intent, "from_token", "")
        to_token = getattr(intent, "to_token", "")
        if from_token == self.quote_token and to_token == self.base_token:
            self._holding_asset = "base"
        elif from_token == self.base_token and to_token == self.quote_token:
            self._holding_asset = "quote"

    def get_persistent_state(self):
        return {
            "prev_rsi": str(self._prev_rsi) if self._prev_rsi is not None else None,
            "last_processed_candle_ts": self._last_processed_candle_ts,
            "holding_asset": self._holding_asset,
            "last_signal": self._last_signal,
        }

    def load_persistent_state(self, state):
        if not state:
            return
        prev_rsi = state.get("prev_rsi")
        self._prev_rsi = Decimal(str(prev_rsi)) if prev_rsi is not None else None
        self._last_processed_candle_ts = state.get("last_processed_candle_ts")
        self._holding_asset = state.get("holding_asset", "quote")
        self._last_signal = state.get("last_signal", "none")

    def supports_teardown(self) -> bool:
        return True

    def get_open_positions(self):
        from almanak.framework.teardown import PositionInfo, PositionType, TeardownPositionSummary

        positions = []
        try:
            market = self.create_market_snapshot()
            base_balance = market.balance(self.base_token)
            if base_balance.balance >= self.min_base_balance:
                positions.append(
                    PositionInfo(
                        position_type=PositionType.TOKEN,
                        position_id="arb_weth_usdc_momentum_weth",
                        chain=self.chain,
                        protocol=self.protocol,
                        value_usd=base_balance.balance_usd,
                        details={"asset": self.base_token, "balance": str(base_balance.balance)},
                    )
                )
        except (ValueError, MarketSnapshotError):
            positions = []

        return TeardownPositionSummary(
            strategy_id=getattr(self, "strategy_id", "arb_weth_usdc_momentum"),
            timestamp=datetime.now(UTC),
            positions=positions,
        )

    def generate_teardown_intents(self, mode=None, market=None) -> list[Intent]:
        from almanak.framework.teardown import TeardownMode

        max_slippage = Decimal("0.03") if mode == TeardownMode.HARD else self._max_slippage()
        return [
            Intent.swap(
                from_token=self.base_token,
                to_token=self.quote_token,
                amount="all",
                max_slippage=max_slippage,
                protocol=self.protocol,
                chain=self.chain,
            )
        ]
