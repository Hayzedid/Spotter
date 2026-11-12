class RoutingInputError(ValueError):
    """The request can't be served as asked (unknown place, no road route, outside forecast range).

    Returned to the client as HTTP 400 with the message shown to the user.
    """


class UpstreamServiceError(RuntimeError):
    """A third-party API needed to answer the request failed. Returned as HTTP 502."""
