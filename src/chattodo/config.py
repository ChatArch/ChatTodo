"Typed environment configuration for ChatTodo."

from chatenv import BaseEnvConfig, EnvField


class ChattodoConfig(BaseEnvConfig):
    "ChatTodo ChatEnv configuration."

    _title = "ChatTodo Configuration"
    _aliases = ["chattodo"]
    _storage_dir = "Chattodo"

    @classmethod
    def test(cls) -> None:
        """Validate schema registration without external side effects."""

        print(f"Testing {cls._title}...")
        print("Schema loaded; no network test is required.")

    CHATTODO_API_KEY = EnvField(
        "CHATTODO_API_KEY",
        desc="API key",
        is_sensitive=True,
    )


__all__ = ["ChattodoConfig"]
