import asyncio
from typing import Literal

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware  # ✅ ADD THIS
from pydantic import BaseModel, Field, field_validator

from app.models.response import APIResponse, ResponseData
from app.services.checker import check_text, warm_tools

app = FastAPI()

# ✅ ADD CORS CONFIG HERE
origins = [
    "http://localhost:5174",
    "http://127.0.0.1:5174",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],   # IMPORTANT (handles OPTIONS)
    allow_headers=["*"],
)


@app.on_event("startup")
async def preload_language_tools() -> None:
    # Pre-warm common tools to reduce cold-start latency on the first /check call.
    await asyncio.to_thread(warm_tools, ("en-US", "en-GB"))

CheckKind = Literal["spelling", "grammar"]


class CheckRequest(BaseModel):
    text: str = ""
    types: list[CheckKind] = Field(
        default_factory=lambda: ["spelling", "grammar"],
        description='Issues to include. Use ["spelling"], ["grammar"], or both (default).',
    )
    language: str | None = Field(
        default=None,
        description='Language variant for checking, e.g. "en-US" or "en-GB". Defaults to "en-US".',
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
    errors = await asyncio.to_thread(
        check_text,
        req.text,
        frozenset(req.types),
        req.language
    )

    return APIResponse(
        status=True,
        response=ResponseData(errors=errors)
    )
