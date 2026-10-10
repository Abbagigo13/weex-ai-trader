import os
from dotenv import load_dotenv

load_dotenv()


class Settings:
    APP_NAME = os.getenv("APP_NAME", "Abbagigo AI Trader")
    ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
    API_PREFIX = os.getenv("API_PREFIX", "/api")

    WEEX_API_KEY = os.getenv("WEEX_API_KEY", "")
    WEEX_API_SECRET = os.getenv("WEEX_API_SECRET", "")
    WEEX_API_PASSPHRASE = os.getenv("WEEX_API_PASSPHRASE", "")

    TRADING_ENABLED = os.getenv("TRADING_ENABLED", "false").lower() == "true"
    PAPER_TRADING = os.getenv("PAPER_TRADING", "true").lower() == "true"


settings = Settings()