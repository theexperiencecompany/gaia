"""Google Maps Geocoding payload the Maps tool reads.

Reference: https://developers.google.com/maps/documentation/geocoding/requests-geocoding#StatusCodes
"""

from pydantic import BaseModel, ConfigDict


class GoogleGeocodeResponse(BaseModel):
    """``GET /maps/api/geocode/json`` — only ``status`` is read.

    Geocoding always sends ``status``; the default marks a body without one, which
    the tool reports rather than treating as connected.
    """

    model_config = ConfigDict(extra="ignore")

    status: str = "UNKNOWN"
