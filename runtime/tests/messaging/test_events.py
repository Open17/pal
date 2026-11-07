from __future__ import annotations

from pal.messaging import EventBus


async def test_subscribers_receive_published_events() -> None:
    bus = EventBus()
    with bus.subscribe() as first, bus.subscribe() as second:
        bus.publish("bot.status", bot="atlas", status="busy")
        for subscription in (first, second):
            event = await subscription.get()
            assert event.type == "bot.status"
            assert event.data == {"bot": "atlas", "status": "busy"}
    assert bus.subscriber_count == 0


async def test_slow_subscribers_drop_oldest_events() -> None:
    bus = EventBus(queue_size=2)
    with bus.subscribe() as subscription:
        for number in range(5):
            bus.publish("tick", n=number)
        assert subscription.dropped == 3
        assert [(await subscription.get()).data["n"] for _ in range(2)] == [3, 4]


def test_publishing_without_subscribers_is_harmless() -> None:
    event = EventBus().publish("tick")
    assert event.to_dict()["type"] == "tick"
