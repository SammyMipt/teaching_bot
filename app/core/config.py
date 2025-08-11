from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    # Telegram / OpenAI
    TELEGRAM_BOT_TOKEN: str
    OPENAI_API_KEY: str | None = None

    # Yandex Disk (WebDAV)
    YD_WEBDAV_URL: str = "https://webdav.yandex.ru"
    YD_LOGIN: str
    YD_PASSWORD: str

    # Роли и коды
    OWNER_IDS: str = ""            # "123,456"
    INSTRUCTOR_IDS: str = ""       # "111,222" (необязательно; можно через регистрацию)
    COURSE_CODE: str = "PHYS-2025" # код для студентов
    INSTRUCTOR_CODE: str = "TA-2025" # код для преподавателей

    # DEV фичи
    DEV_ALLOW_AS: bool = True      # разрешить /as и /impersonate владельцу (dev)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
    )

    @property
    def owner_ids(self) -> set[int]:
        return {int(x) for x in self.OWNER_IDS.split(",") if x.strip()}

    @property
    def instructor_ids(self) -> set[int]:
        base = {int(x) for x in self.INSTRUCTOR_IDS.split(",") if x.strip()}
        return base | self.owner_ids  # владельцу — все права

settings = Settings()
