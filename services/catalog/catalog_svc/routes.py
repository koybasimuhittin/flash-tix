from dataclasses import dataclass

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import TypeAdapter
from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from catalog_svc.cache import CatalogCache, detail_key, list_key, normalize_list_query
from catalog_svc.config import CatalogSettings
from catalog_svc.models import Event, Section
from catalog_svc.schemas import EventDetail, EventIn, EventPatch, EventSummary, SectionOut
from flashtix_common.seats import capacity
from flashtix_common.security import Principal, require_organizer


@dataclass
class CatalogState:
    """Everything the routes need, created in the lifespan and kept at `app.state.catalog`
    (namespaced so the monolith can hold every service's state side by side).

    Routes open a DB session only around their queries, never across Redis calls, so a
    pooled connection is never held while waiting on the cache."""

    settings: CatalogSettings
    engine: AsyncEngine
    sessionmaker: async_sessionmaker[AsyncSession]
    cache: CatalogCache


router = APIRouter(prefix="/api/events", tags=["catalog"])

_summaries = TypeAdapter(list[EventSummary])


def get_state(request: Request) -> CatalogState:
    return request.app.state.catalog


def _json(body: str | bytes, cache_status: str, status_code: int = 200) -> Response:
    """X-Cache: HIT | MISS | BYPASS on every response; load tests read it."""
    headers = {"X-Cache": cache_status}
    return Response(body, status_code=status_code, media_type="application/json", headers=headers)


def _summary_query() -> Select:
    """Events with min price and capacity aggregated from their sections in one query."""
    totals = (
        select(
            Section.event_id,
            func.min(Section.price_cents).label("min_price_cents"),
            func.sum(Section.rows * Section.seats_per_row).label("capacity"),
        )
        .group_by(Section.event_id)
        .subquery()
    )
    return select(
        Event.id,
        Event.title,
        Event.venue,
        Event.city,
        Event.starts_at,
        Event.sales_open_at,
        totals.c.min_price_cents,
        totals.c.capacity,
    ).join(totals, totals.c.event_id == Event.id)


async def _summaries_json(state: CatalogState, stmt: Select) -> bytes:
    async with state.sessionmaker() as session:
        rows = (await session.execute(stmt)).mappings().all()
    return _summaries.dump_json([EventSummary.model_validate(dict(row)) for row in rows])


def _detail(event: Event) -> EventDetail:
    return EventDetail(
        id=event.id,
        title=event.title,
        description=event.description,
        venue=event.venue,
        city=event.city,
        starts_at=event.starts_at,
        sales_open_at=event.sales_open_at,
        min_price_cents=min(section.price_cents for section in event.sections),
        capacity=capacity(event.sections),
        sections=[SectionOut.model_validate(section) for section in event.sections],
    )


def _escape_like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _not_found() -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, detail={"code": "EVENT_NOT_FOUND"})


@router.get("", response_model=list[EventSummary])
async def list_events(
    city: str | None = Query(default=None, max_length=100),
    q: str | None = Query(default=None, max_length=100),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=10_000),
    state: CatalogState = Depends(get_state),
) -> Response:
    """Upcoming events ordered by start time. Cached per normalized query."""
    query = normalize_list_query(city, q, limit, offset)
    cache = state.cache
    key = None
    # Read the version *before* the DB: if a write lands meanwhile, this result is stored
    # under the old version, which nobody reads any more. No version (Redis down) → no cache.
    version = await cache.list_version() if cache.enabled else None
    if version is not None:
        key = list_key(version, query)
        if (cached := await cache.get(key)) is not None:
            return _json(cached, "HIT")

    stmt = _summary_query().where(Event.starts_at > func.now())
    if query["city"]:
        stmt = stmt.where(func.lower(Event.city) == query["city"])
    if query["q"]:
        pattern = f"%{_escape_like(query['q'])}%"
        stmt = stmt.where(or_(Event.title.ilike(pattern), Event.venue.ilike(pattern)))
    body = await _summaries_json(
        state, stmt.order_by(Event.starts_at, Event.id).limit(limit).offset(offset)
    )

    if key is None:
        return _json(body, "BYPASS")
    await cache.set(key, body.decode())
    return _json(body, "MISS")


# Registered before /{event_id}, otherwise "mine" would be parsed as an event id (422).
@router.get("/mine", response_model=list[EventSummary])
async def my_events(
    principal: Principal = Depends(require_organizer),
    state: CatalogState = Depends(get_state),
) -> Response:
    """The organizer's own events, past ones included, newest first. Never cached: it is
    per-user and organizers expect their just-created event to show up immediately."""
    stmt = (
        _summary_query()
        .where(Event.created_by == principal.user_id)
        .order_by(Event.starts_at.desc(), Event.id.desc())
        .limit(500)
    )
    return _json(await _summaries_json(state, stmt), "BYPASS")


@router.get("/{event_id}", response_model=EventDetail)
async def get_event(event_id: int, state: CatalogState = Depends(get_state)) -> Response:
    cache = state.cache
    # Version first, then the DB (see cache.py): a late write lands under an outdated key.
    version = await cache.event_version(event_id) if cache.enabled else None
    key = detail_key(event_id, version) if version is not None else None
    if key is not None and (cached := await cache.get(key)) is not None:
        return _json(cached, "HIT")

    async with state.sessionmaker() as session:
        event = await session.get(Event, event_id)  # sections load eagerly (selectin)
    if event is None:
        raise _not_found()
    body = _detail(event).model_dump_json()

    if key is None:
        return _json(body, "BYPASS")
    await cache.set(key, body)
    return _json(body, "MISS")


@router.post("", status_code=status.HTTP_201_CREATED, response_model=EventDetail)
async def create_event(
    body: EventIn,
    principal: Principal = Depends(require_organizer),
    state: CatalogState = Depends(get_state),
) -> Response:
    event = Event(
        title=body.title,
        description=body.description,
        venue=body.venue,
        city=body.city,
        starts_at=body.starts_at,
        sales_open_at=body.sales_open_at,
        created_by=principal.user_id,
        sections=[
            Section(**section.model_dump(), sort_order=index)
            for index, section in enumerate(body.sections)
        ],
    )
    async with state.sessionmaker() as session:
        session.add(event)
        await session.commit()
    await state.cache.invalidate(event.id)  # the new event must appear in cached lists
    return _json(_detail(event).model_dump_json(), "BYPASS", status.HTTP_201_CREATED)


@router.patch("/{event_id}", response_model=EventDetail)
async def update_event(
    event_id: int,
    body: EventPatch,
    principal: Principal = Depends(require_organizer),
    state: CatalogState = Depends(get_state),
) -> Response:
    async with state.sessionmaker() as session:
        event = await session.get(Event, event_id)
        if event is None:
            raise _not_found()
        if event.created_by != principal.user_id:
            raise HTTPException(status.HTTP_403_FORBIDDEN, detail={"code": "NOT_EVENT_OWNER"})
        for field, value in body.model_dump(exclude_unset=True).items():
            if value is not None:  # omitted or null fields stay unchanged
                setattr(event, field, value)
        if event.sales_open_at > event.starts_at:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={"code": "SALES_OPEN_AFTER_START"},
            )
        await session.commit()
    await state.cache.invalidate(event.id)
    return _json(_detail(event).model_dump_json(), "BYPASS")
