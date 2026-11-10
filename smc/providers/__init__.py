from .base import AuthError, DataError, Provider  # noqa: F401


def get_provider(market, **kw):
    """Factory: market.provider -> provider instance."""
    if market.provider == "upstox":
        from .upstox import UpstoxProvider
        return UpstoxProvider(market=market.name, **kw)
    if market.provider == "binance":
        from .binance import BinanceProvider
        return BinanceProvider(**kw)
    if market.provider == "yahoo":
        from .yahoo import YahooProvider
        return YahooProvider(**kw)
    raise ValueError(f"unknown provider {market.provider}")
