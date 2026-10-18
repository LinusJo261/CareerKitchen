"""Bounded, explicitly consented navigation assistance; no account context."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class NavigationChatIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    message: str = Field(min_length=1, max_length=2000)
    consent_to_gemini: Literal[True]


class NavigationLink(BaseModel):
    label: str
    path: str


class NavigationChatOut(BaseModel):
    reply: str
    links: list[NavigationLink]
    version: Literal[1] = 1
