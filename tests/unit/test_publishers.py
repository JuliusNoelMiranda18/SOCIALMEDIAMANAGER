from datetime import UTC, datetime, timedelta
from email.utils import format_datetime

import httpx
import pytest
from sqlalchemy import select

from app.models import PlatformToken
from app.publishers import PublishRequest, get_publisher
from app.publishers.fake import FakeInstagramPublisher, FakeXPublisher, retry_after_seconds

REQ = PublishRequest("x", "hello", "http://api:8000/media/1_x.png", "key-1")


class Fake:
    """MockTransport handler: serves /oauth/token and replies to /v1/posts from a script."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.posts: list[httpx.Request] = []
        self.issued: list[str] = []
        self.on_post = lambda: None

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oauth/token":
            self.issued.append(f"tok{len(self.issued)}")
            return httpx.Response(200, json={"access_token": self.issued[-1]})
        self.on_post()
        self.posts.append(request)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply

    def publisher(self, cls=FakeXPublisher):
        return cls(httpx.Client(transport=httpx.MockTransport(self), base_url="http://fake"))


def http_date(seconds: int) -> str:
    return format_datetime(datetime.now(UTC) + timedelta(seconds=seconds), usegmt=True)


CASES = [
    (httpx.Response(201, json={"id": "p1"}), "accepted"),
    (httpx.Response(429, headers={"Retry-After": "7"}), "rate_limited"),
    (httpx.Response(429, headers={"Retry-After": http_date(30)}), "rate_limited"),
    (httpx.Response(429), "retryable"),
    (httpx.Response(429, headers={"Retry-After": "soon"}), "retryable"),
    (httpx.Response(503), "retryable"),
    (httpx.ReadTimeout("slow"), "retryable"),
    (httpx.ConnectError("down"), "retryable"),
    (httpx.Response(400), "fatal"),
    (httpx.Response(422), "fatal"),
]


@pytest.mark.parametrize("reply,kind", CASES)
def test_status_mapping_one_request(reply, kind):
    fake = Fake(reply)
    out = fake.publisher().publish(REQ)
    assert out.kind == kind
    assert len(fake.posts) == 1
    sent = fake.posts[0]
    assert sent.headers["Idempotency-Key"] == "key-1"
    assert sent.headers["Authorization"] == "Bearer tok0"


def test_accepted_and_retry_after_values():
    def one(reply):
        return Fake(reply).publisher().publish(REQ)

    assert one(httpx.Response(201, json={"id": "p1"})).platform_post_id == "p1"
    assert one(httpx.Response(429, headers={"Retry-After": "7"})).wait_seconds == 7
    date = one(httpx.Response(429, headers={"Retry-After": http_date(30)}))
    assert 28 <= date.wait_seconds <= 30


def test_retry_after_parser():
    assert retry_after_seconds("0") == 0
    assert retry_after_seconds(http_date(-100)) == 0  # past date: go now
    assert retry_after_seconds("Wed, 21 Oct 2015 07:28:00 -0000") == 0
    for bad in [None, "", "-1", "1.5", "garbage", "Mon, 99 Foo 2020"]:
        assert retry_after_seconds(bad) is None


def test_401_refreshes_token_once(db):
    fake = Fake(httpx.Response(401), httpx.Response(201, json={"id": "p1"}))
    assert fake.publisher().publish(REQ).kind == "accepted"
    assert [p.headers["Authorization"] for p in fake.posts] == ["Bearer tok0", "Bearer tok1"]
    # the refreshed token replaced the stored one (encrypted)
    row = db.scalars(select(PlatformToken)).one()
    assert row.platform == "x" and b"tok1" not in row.ciphertext
    fake2 = Fake(httpx.Response(201, json={"id": "p2"}))
    fake2.publisher().publish(REQ)
    assert fake2.issued == [] and fake2.posts[0].headers["Authorization"] == "Bearer tok1"


def test_401_twice_is_fatal():
    fake = Fake(httpx.Response(401), httpx.Response(401))
    assert fake.publisher().publish(REQ).kind == "fatal"
    assert len(fake.posts) == 2 and len(fake.issued) == 2


def test_platform_rules_are_fatal_without_a_request():
    fake = Fake()
    long_x = PublishRequest("x", "a" * 281, None, "k")
    assert fake.publisher().publish(long_x).kind == "fatal"
    no_img = PublishRequest("instagram", "hi", None, "k")
    assert fake.publisher(FakeInstagramPublisher).publish(no_img).kind == "fatal"
    assert fake.posts == [] and fake.issued == []


def test_factory():
    assert isinstance(get_publisher("x"), FakeXPublisher)
    assert isinstance(get_publisher("instagram"), FakeInstagramPublisher)


@pytest.mark.parametrize(
    "corrupt",
    [
        {"nonce": b"\x00" * 4},  # wrong length: ValueError, not InvalidTag (ISSUE-006)
        {"nonce": b"\x00" * 12},
        {"ciphertext": b"short"},
        {"platform": "instagram"},  # wrong AAD: a row moved to another platform
    ],
)
def test_undecryptable_token_row_fetches_fresh_token(db, corrupt):
    Fake(httpx.Response(201, json={"id": "p1"})).publisher().publish(REQ)  # stores tok0 for x
    platform = corrupt.pop("platform", "x")
    db.execute(
        PlatformToken.__table__.update()
        .where(PlatformToken.platform == "x")
        .values(platform=platform, **corrupt)
    )
    db.commit()
    req = REQ if platform == "x" else PublishRequest(platform, "hi", "http://i/1.png", "k")
    cls = FakeXPublisher if platform == "x" else FakeInstagramPublisher
    fake = Fake(httpx.Response(201, json={"id": "p2"}))
    assert fake.publisher(cls).publish(req).kind == "accepted"
    assert fake.issued == ["tok0"]  # a fresh fetch from this fake
    db.expire_all()
    assert len(db.scalars(select(PlatformToken)).all()) == 1


@pytest.mark.parametrize(
    "reply",
    [
        httpx.Response(201, json={}),
        httpx.Response(201, text="ok"),
        httpx.Response(200, json=["p1"]),
        httpx.Response(201, json={"id": 7}),
        httpx.Response(201, json={"id": ""}),
    ],
)
def test_malformed_2xx_is_retryable(reply):
    out = Fake(reply).publisher().publish(REQ)
    assert (out.kind, out.reason) == ("retryable", "malformed response")


@pytest.mark.parametrize(
    "token_reply",
    [
        httpx.Response(200, json={}),
        httpx.Response(200, text="<html>"),
        httpx.Response(200, json={"access_token": None}),
        httpx.Response(200, json=[1]),
    ],
)
def test_bad_token_response_is_retryable(token_reply):
    def handler(request):
        assert request.url.path == "/oauth/token"  # no post is sent without a token
        return token_reply

    client = httpx.Client(transport=httpx.MockTransport(handler), base_url="http://fake")
    out = FakeXPublisher(client).publish(REQ)
    assert (out.kind, out.reason) == ("retryable", "bad token response")
