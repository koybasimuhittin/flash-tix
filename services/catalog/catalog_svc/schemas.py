from typing import Annotated

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints, model_validator

SectionCode = Annotated[str, StringConstraints(pattern=r"^[A-Z]{1,3}$")]
Text100 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
Text200 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


class SectionIn(BaseModel):
    code: SectionCode
    name: Text100
    price_cents: int = Field(ge=0, le=10_000_000)
    rows: int = Field(ge=1, le=50)
    seats_per_row: int = Field(ge=1, le=60)


class EventIn(BaseModel):
    title: Text200
    description: str = Field(default="", max_length=5000)
    venue: Text200
    city: Text100
    starts_at: AwareDatetime
    sales_open_at: AwareDatetime
    sections: list[SectionIn] = Field(min_length=1, max_length=26)

    @model_validator(mode="after")
    def check_event(self) -> "EventIn":
        codes = [section.code for section in self.sections]
        if len(codes) != len(set(codes)):
            raise ValueError("section codes must be unique within an event")
        if self.sales_open_at > self.starts_at:
            raise ValueError("sales_open_at must not be after starts_at")
        return self


class EventPatch(BaseModel):
    """Used to (re)schedule a flash sale: `sales_open_at = now + N s`."""

    title: Text200 | None = None
    description: str | None = Field(default=None, max_length=5000)
    starts_at: AwareDatetime | None = None
    sales_open_at: AwareDatetime | None = None


class SectionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    code: str
    name: str
    price_cents: int
    rows: int
    seats_per_row: int
    sort_order: int


class EventSummary(BaseModel):
    """One item of `GET /api/events` and `GET /api/events/mine`."""

    id: int
    title: str
    venue: str
    city: str
    starts_at: AwareDatetime
    sales_open_at: AwareDatetime
    min_price_cents: int
    capacity: int


class EventDetail(EventSummary):
    description: str
    sections: list[SectionOut]
