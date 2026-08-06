from app.events.events import Event
from app.events.event_bus import EventBus


def test_event_bus_publish():

    bus = EventBus()

    received = []


    def handler(event):

        received.append(event.data)


    bus.subscribe(
        "TEST_EVENT",
        handler,
    )


    bus.publish(
        Event(
            "TEST_EVENT",
            {
                "value": 123
            }
        )
    )


    assert received[0]["value"] == 123