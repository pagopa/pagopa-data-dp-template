from .base import AppConfig

DEV_CONFIG = AppConfig(env="dev", log_level="DEBUG", write_enabled=False)
