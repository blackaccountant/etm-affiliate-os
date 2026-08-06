"""
Event Bus

Central communication layer.
"""


class EventBus:

    def __init__(self):

        self.listeners = {}


    def subscribe(
        self,
        event_name,
        callback,
    ):

        if event_name not in self.listeners:

            self.listeners[event_name] = []

        self.listeners[event_name].append(callback)


    def publish(
        self,
        event,
    ):

        listeners = self.listeners.get(
            event.name,
            []
        )

        for callback in listeners:

            callback(event)