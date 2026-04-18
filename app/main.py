import asyncio
from typing import Literal

from fastapi import FastAPI
from pydantic import BaseModel, Field, field_validator

from app.models.response import APIResponse, ResponseData
from app.services.checker import check_text

app = FastAPI()

CheckKind = Literal["spelling", "grammar"]


class CheckRequest(BaseModel):
    text: str = ""
    types: list[CheckKind] = Field(
        default_factory=lambda: ["spelling", "grammar"],
        description='Issues to include. Use ["spelling"], ["grammar"], or both (default).',
    )

    @field_validator("text", mode="before")
    @classmethod
    def text_none_to_empty(cls, v: object) -> str:
        return "" if v is None else str(v)

    @field_validator("types", mode="before")
    @classmethod
    def types_default_if_empty(cls, v: object) -> list[str]:
        if v is None or v == []:
            return ["spelling", "grammar"]
        return list(v)

    @field_validator("types", mode="after")
    @classmethod
    def types_dedupe_ordered(cls, v: list[str]) -> list[str]:
        order: tuple[CheckKind, ...] = ("spelling", "grammar")
        seen: set[str] = set()
        out: list[str] = []
        for kind in order:
            if kind in v and kind not in seen:
                out.append(kind)
                seen.add(kind)
        return out


@app.post("/check", response_model=APIResponse)
async def check_spelling_grammar(req: CheckRequest):
    errors = await asyncio.to_thread(check_text, req.text, frozenset(req.types))

    return APIResponse(
        status=True,
        response=ResponseData(errors=errors)
    )