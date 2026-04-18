from pydantic import BaseModel
from typing import List


class Description(BaseModel):
    en: str


class ErrorItem(BaseModel):
    id: str
    type: str                # spelling | grammar
    bad: str
    better: List[str]
    offset: int
    length: int
    description: Description


class ResponseData(BaseModel):
    errors: List[ErrorItem]


class APIResponse(BaseModel):
    status: bool
    response: ResponseData
