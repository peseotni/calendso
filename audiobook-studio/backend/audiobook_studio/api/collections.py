"""User-defined collections (shelves)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Book, Collection
from ..schemas import CollectionBooks, CollectionIn, CollectionOut
from .common import get_or_404

router = APIRouter(prefix="/api/collections", tags=["collections"])


def _out(collection: Collection) -> CollectionOut:
    books = sorted(collection.books, key=lambda b: b.added_at, reverse=True)
    return CollectionOut(
        id=collection.id,
        name=collection.name,
        description=collection.description,
        color=collection.color,
        created_at=collection.created_at,
        book_count=len(books),
        cover_book_ids=[b.id for b in books if b.cover_path][:4],
    )


@router.get("", response_model=list[CollectionOut])
def list_collections(session: Session = Depends(get_db)):
    return [_out(c) for c in session.query(Collection).order_by(Collection.name)]


@router.post("", response_model=CollectionOut)
def create_collection(body: CollectionIn, session: Session = Depends(get_db)):
    if session.query(Collection).filter(Collection.name == body.name.strip()).first():
        raise HTTPException(409, "A collection with this name already exists.")
    collection = Collection(name=body.name.strip(), description=body.description, color=body.color)
    session.add(collection)
    session.commit()
    return _out(collection)


@router.patch("/{collection_id}", response_model=CollectionOut)
def update_collection(collection_id: int, body: CollectionIn, session: Session = Depends(get_db)):
    collection = get_or_404(session, Collection, collection_id, "Collection")
    clash = session.query(Collection).filter(Collection.name == body.name.strip(), Collection.id != collection_id).first()
    if clash:
        raise HTTPException(409, "A collection with this name already exists.")
    collection.name = body.name.strip()
    collection.description = body.description
    collection.color = body.color
    session.commit()
    return _out(collection)


@router.delete("/{collection_id}")
def delete_collection(collection_id: int, session: Session = Depends(get_db)):
    collection = get_or_404(session, Collection, collection_id, "Collection")
    session.delete(collection)
    session.commit()
    return {"ok": True}


@router.post("/{collection_id}/books", response_model=CollectionOut)
def add_books(collection_id: int, body: CollectionBooks, session: Session = Depends(get_db)):
    collection = get_or_404(session, Collection, collection_id, "Collection")
    for book in session.query(Book).filter(Book.id.in_(body.book_ids)):
        if book not in collection.books:
            collection.books.append(book)
    session.commit()
    return _out(collection)


@router.delete("/{collection_id}/books/{book_id}", response_model=CollectionOut)
def remove_book(collection_id: int, book_id: int, session: Session = Depends(get_db)):
    collection = get_or_404(session, Collection, collection_id, "Collection")
    book = session.get(Book, book_id)
    if book is not None and book in collection.books:
        collection.books.remove(book)
        session.commit()
    return _out(collection)
