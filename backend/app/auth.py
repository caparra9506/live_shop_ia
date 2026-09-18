from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError
from sqlalchemy import text

from app.config import settings
from app.db import LiveshopSessionLocal

bearer_scheme = HTTPBearer()


def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme)) -> dict:
    """Valida el mismo JWT que emite el login de LiveShop (auth.module.ts),
    para que el panel comparta sesion con el admin principal."""
    token = credentials.credentials
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token invalido o expirado",
        )
    return payload


def require_store_access(store_id: int, user: dict) -> None:
    """El admin de LiveShop (Camilo) puede ver cualquier tienda. Un dueno de
    tienda normal (rol 'user') solo puede ver la suya - se valida contra el
    dueno real en el MySQL de LiveShop, no confiando en lo que mande el front."""
    if user.get("role") == "admin":
        return
    db = LiveshopSessionLocal()
    try:
        row = db.execute(
            text("SELECT ownerId FROM store WHERE id = :store_id"), {"store_id": store_id}
        ).first()
    finally:
        db.close()
    if not row or row[0] != user.get("id"):
        raise HTTPException(status_code=403, detail="No tienes acceso a esta tienda")
