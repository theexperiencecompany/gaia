from urllib.parse import parse_qs, urlencode, urlparse, urlunparse


def add_query_param(url: str, key: str, value: str) -> str:
    """
    Add a query parameter to a URL.

    Args:
        url (str): The original URL.
        key (str): The query parameter key.
        value (str): The query parameter value.

    Returns:
        str: The updated URL with the new query parameter.
    """
    parsed_url = urlparse(url)
    query_params = parse_qs(parsed_url.query)

    # Add or update the query parameter
    query_params[key] = [value]

    # Reconstruct the URL with the updated query parameters
    new_query = urlencode(query_params, doseq=True)
    updated_url = urlunparse(
        (
            parsed_url.scheme,
            parsed_url.netloc,
            parsed_url.path,
            parsed_url.params,
            new_query,
            parsed_url.fragment,
        )
    )

    return updated_url
