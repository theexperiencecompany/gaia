from urllib.parse import parse_qs, urlencode, urlparse, urlunparse


def add_query_param(url: str, key: str, value: str) -> str:
    parsed_url = urlparse(url)
    query_params = parse_qs(parsed_url.query)

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
