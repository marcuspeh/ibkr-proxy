from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # IBKR Gateway connection settings
    IBKR_HOST: str = "127.0.0.1"
    IBKR_PORT: int = 4002
    IBKR_CLIENT_ID: int = 1
    
    # Webhook settings
    WEBHOOK_URL: str = "http://127.0.0.1:8000/webhook"
    
    # Proxy server settings
    PROXY_PORT: int = 5001
    PROXY_HOST: str = "0.0.0.0"

    class Config:
        env_file = ".env"

settings = Settings()
