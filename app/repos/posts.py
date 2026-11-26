from sqlalchemy.orm import Session

from app.models import Post


def add(session: Session, **fields) -> Post:
    post = Post(**fields)
    session.add(post)
    session.flush()
    return post


def get(session: Session, post_id: int) -> Post | None:
    return session.get(Post, post_id)
