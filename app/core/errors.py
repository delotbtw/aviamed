from fastapi import HTTPException, status


def not_implemented() -> HTTPException:
    """Placeholder for endpoints that are in the skeleton but have no logic yet."""
    return HTTPException(status.HTTP_501_NOT_IMPLEMENTED, "Not implemented")
