"""Price-book maintenance behind the simplified administration workflow.

An administrator edits one product's prices; the price book itself stays out of
sight. Because a store's assignment window may not overlap another, a price
change is applied by *sliding* to a new version: the live assignment is closed
at the moment of the change, a fresh version is opened from that same moment,
and every price the edit did not touch is copied across verbatim.

Copying is the part that matters. A missed row would silently reprice a product
or drop an option surcharge, so both `price_book_item` and
`price_book_option_item` are carried over as a whole.

Historical orders keep their own immutable snapshots and are unaffected.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import PriceBookStatus
from app.core.errors import ConflictError
from app.modules.catalog.models import (
    PriceBook,
    PriceBookItem,
    PriceBookOptionItem,
    StorePriceBookAssignment,
)
from app.modules.organization.models import Store
from app.persistence.base import utc_now

DEFAULT_PRICE_BOOK_CODE = "standard"


@dataclass(frozen=True, slots=True)
class ProductPriceChange:
    """The prices to apply for a single product in the next price-book version."""

    product_id: UUID
    price_minor: int
    # option_value_id -> surcharge. Replaces every option price previously
    # recorded for this product; an option left out is treated as removed.
    option_prices: dict[UUID, int] = field(default_factory=dict)


async def get_active_assignment(
    session: AsyncSession,
    store_id: UUID,
    *,
    at: datetime | None = None,
) -> tuple[PriceBook, StorePriceBookAssignment] | None:
    """Return the price book in force for a store, with its assignment."""
    effective_at = at or utc_now()
    row = (
        await session.execute(
            select(PriceBook, StorePriceBookAssignment)
            .join(StorePriceBookAssignment, StorePriceBookAssignment.price_book_id == PriceBook.id)
            .where(
                StorePriceBookAssignment.store_id == store_id,
                StorePriceBookAssignment.valid_from <= effective_at,
                or_(
                    StorePriceBookAssignment.valid_to.is_(None),
                    StorePriceBookAssignment.valid_to > effective_at,
                ),
                PriceBook.status == PriceBookStatus.PUBLISHED,
            )
            .order_by(StorePriceBookAssignment.valid_from.desc())
        )
    ).first()
    if row is None:
        return None
    price_book, assignment = row
    return price_book, assignment


async def ensure_price_book(
    session: AsyncSession,
    store: Store,
    tenant_id: UUID,
) -> PriceBook:
    """Return the store's live price book, creating an empty one if needed.

    A newly created store has no prices yet, so this gives the product editor
    something to write into on the very first save.
    """
    active = await get_active_assignment(session, store.id)
    if active is not None:
        return active[0]

    price_book = PriceBook(
        tenant_id=tenant_id,
        code=DEFAULT_PRICE_BOOK_CODE,
        version=await _next_version(session, tenant_id, DEFAULT_PRICE_BOOK_CODE),
        currency=store.currency,
        prices_include_tax=True,
        status=PriceBookStatus.PUBLISHED,
    )
    session.add(price_book)
    try:
        await session.flush()
    except IntegrityError as exc:  # pragma: no cover - guarded by _next_version
        raise ConflictError("price_book_exists", "The price book version already exists") from exc
    session.add(
        StorePriceBookAssignment(
            store_id=store.id,
            price_book_id=price_book.id,
            valid_from=utc_now(),
            valid_to=None,
        )
    )
    await session.flush()
    return price_book


async def _next_version(session: AsyncSession, tenant_id: UUID, code: str) -> int:
    highest = await session.scalar(
        select(func.max(PriceBook.version)).where(
            PriceBook.tenant_id == tenant_id,
            PriceBook.code == code,
        )
    )
    return int(highest or 0) + 1


async def apply_product_price(
    session: AsyncSession,
    store: Store,
    tenant_id: UUID,
    change: ProductPriceChange,
) -> PriceBook:
    """Slide the store onto a new price-book version carrying `change`.

    Returns the newly published price book. Every other product's prices, and
    every other product's option surcharges, are preserved exactly.
    """
    # Serialise concurrent price edits for this store so two saves cannot each
    # open an assignment starting at the same moment.
    await session.scalar(select(Store.id).where(Store.id == store.id).with_for_update())

    await ensure_price_book(session, store, tenant_id)
    active = await get_active_assignment(session, store.id)
    if active is None:  # pragma: no cover - ensure_price_book just created one
        raise ConflictError("price_book_unavailable", "No published price book is active")
    current, assignment = active

    carried_items = {
        item.product_id: item.price_minor
        for item in (
            await session.scalars(
                select(PriceBookItem).where(PriceBookItem.price_book_id == current.id)
            )
        ).all()
        if item.product_id != change.product_id
    }
    carried_options = [
        (option.product_id, option.option_value_id, option.price_delta_minor)
        for option in (
            await session.scalars(
                select(PriceBookOptionItem).where(PriceBookOptionItem.price_book_id == current.id)
            )
        ).all()
        if option.product_id != change.product_id
    ]

    changed_at = utc_now()
    if assignment.valid_from >= changed_at:
        # The live assignment starts now or later (a store created in the same
        # request). Rewrite it in place instead of opening a zero-width window.
        return await _replace_prices(
            session,
            current,
            change=change,
            carried_items=carried_items,
            carried_options=carried_options,
        )

    successor = PriceBook(
        tenant_id=tenant_id,
        code=current.code,
        version=await _next_version(session, tenant_id, current.code),
        currency=current.currency,
        prices_include_tax=current.prices_include_tax,
        status=PriceBookStatus.PUBLISHED,
    )
    session.add(successor)
    try:
        await session.flush()
    except IntegrityError as exc:  # pragma: no cover - guarded by _next_version
        raise ConflictError("price_book_exists", "The price book version already exists") from exc

    # Close the outgoing window before opening the new one: the store may not
    # hold two overlapping assignments.
    await session.execute(
        update(StorePriceBookAssignment)
        .where(StorePriceBookAssignment.id == assignment.id)
        .values(valid_to=changed_at)
    )
    session.add(
        StorePriceBookAssignment(
            store_id=store.id,
            price_book_id=successor.id,
            valid_from=changed_at,
            valid_to=None,
        )
    )

    session.add_all(
        PriceBookItem(
            price_book_id=successor.id,
            product_id=product_id,
            price_minor=price_minor,
        )
        for product_id, price_minor in carried_items.items()
    )
    session.add_all(
        PriceBookOptionItem(
            price_book_id=successor.id,
            product_id=product_id,
            option_value_id=option_value_id,
            price_delta_minor=price_delta_minor,
        )
        for product_id, option_value_id, price_delta_minor in carried_options
    )
    _add_change(session, successor.id, change)
    await session.flush()
    return successor


async def _replace_prices(
    session: AsyncSession,
    price_book: PriceBook,
    *,
    change: ProductPriceChange,
    carried_items: dict[UUID, int],
    carried_options: list[tuple[UUID, UUID, int]],
) -> PriceBook:
    """Rewrite this product's rows inside a price book nothing has quoted yet."""
    del carried_items, carried_options  # untouched rows stay where they are
    await session.execute(
        PriceBookOptionItem.__table__.delete().where(
            PriceBookOptionItem.price_book_id == price_book.id,
            PriceBookOptionItem.product_id == change.product_id,
        )
    )
    await session.execute(
        PriceBookItem.__table__.delete().where(
            PriceBookItem.price_book_id == price_book.id,
            PriceBookItem.product_id == change.product_id,
        )
    )
    await session.flush()
    _add_change(session, price_book.id, change)
    await session.flush()
    return price_book


def _add_change(session: AsyncSession, price_book_id: UUID, change: ProductPriceChange) -> None:
    session.add(
        PriceBookItem(
            price_book_id=price_book_id,
            product_id=change.product_id,
            price_minor=change.price_minor,
        )
    )
    session.add_all(
        PriceBookOptionItem(
            price_book_id=price_book_id,
            product_id=change.product_id,
            option_value_id=option_value_id,
            price_delta_minor=price_delta_minor,
        )
        for option_value_id, price_delta_minor in change.option_prices.items()
    )
