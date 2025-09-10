def to_urlsafe_b64(token: str) -> str:
    """Convert Base64 token to URL-safe variant by replacing special chars.

    This mirrors the production fix to avoid header parsing issues on the server
    side when tokens include '/' or '+'. Padding ('=') is preserved.
    """
    if not token:
        return token
    return token.replace('/', '_').replace('+', '-')


def to_standard_b64(token: str) -> str:
    """Convert Base64 URL-safe token to standard Base64 (+,/), with padding.

    Some environments return URL-safe tokens while the server expects standard
    Base64. This helper normalizes by replacing '-'->'+' and '_'->'/'.
    Padding is added to a multiple of 4 if missing.
    """
    if not token:
        return token
    t = token.replace('-', '+').replace('_', '/')
    # Ensure padding length multiple of 4
    pad_len = (-len(t)) % 4
    if pad_len:
        t = t + ("=" * pad_len)
    return t
