"""Bounded, explicitly consented navigation assistance; no account context."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class NavigationTurn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, strict=True)

    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4000)

    @model_validator(mode="after")
    def user_message_limit(self) -> "NavigationTurn":
        if self.role == "user" and len(self.content) > 2000:
            raise ValueError("User history entries exceed the limit")
        return self


class NavigationChatIn(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        strict=True,
        json_schema_extra={
            "examples": [
                {"message": "How do I start finding jobs?", "consent_to_gemini": True, "history": []}
            ]
        },
    )

    message: str = Field(min_length=1, max_length=2000)
    consent_to_gemini: Literal[True]
    history: list[NavigationTurn] = Field(default_factory=list, max_length=10)

    @field_validator("consent_to_gemini", mode="before")
    @classmethod
    def explicit_consent(cls, value: object) -> object:
        if value is not True:
            raise ValueError("Explicit consent is required")
        return value

    @model_validator(mode="after")
    def bounded_completed_history(self) -> "NavigationChatIn":
        if len(self.history) % 2 or any(
            turn.role != ("user" if index % 2 == 0 else "assistant")
            for index, turn in enumerate(self.history)
        ):
            raise ValueError("History must contain completed user/assistant pairs")
        if len(self.message) + sum(len(turn.content) for turn in self.history) > 12000:
            raise ValueError("Conversation context exceeds the limit")
        return self


class NavigationLink(BaseModel):
    label: str
    path: str


class NavigationChatOut(BaseModel):
    reply: str = Field(min_length=1, max_length=4000)
    links: list[NavigationLink] = Field(max_length=3)
    version: Literal[1] = 1
