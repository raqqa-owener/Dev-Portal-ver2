from fastapi import HTTPException
from app.repos.errors import NotFound, Conflict, Validation, Transient


def to_problem(e: Exception) -> HTTPException:
    if isinstance(e, Validation):
        raise HTTPException(status_code=400, detail={"title": "Validation", "detail": str(e)})
    if isinstance(e, NotFound):
        raise HTTPException(status_code=404, detail={"title": "Not Found", "detail": str(e)})
    if isinstance(e, Conflict):
        raise HTTPException(status_code=409, detail={"title": "Conflict", "detail": str(e)})
    if isinstance(e, Transient):
        raise HTTPException(status_code=503, detail={"title": "Transient", "detail": str(e)})
    raise HTTPException(status_code=500, detail={"title": "Internal", "detail": str(e)})