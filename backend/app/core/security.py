from .config import settings


def trading_is_allowed() -> bool:
    """
    Safety gate for order execution.

    Real trading requires:
    - TRADING_ENABLED=true
    - PAPER_TRADING=false
    - WEEX credentials present
    """

    if not settings.TRADING_ENABLED:
        return False

    if settings.PAPER_TRADING:
        return False

    if not settings.WEEX_API_KEY:
        return False

    if not settings.WEEX_API_SECRET:
        return False

    if not settings.WEEX_API_PASSPHRASE:
        return False

    return True