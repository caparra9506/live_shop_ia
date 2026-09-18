from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.db import get_liveshop_db, get_ai_db
from app.models import CommentAiLog
from app.mysql_tools import list_ai_draft_logs

router = APIRouter(prefix="/ai-usage", tags=["ai-usage"])


@router.get("/product-drafts")
def read_product_draft_logs(
    limit: int = 100,
    db: Session = Depends(get_liveshop_db),
    _user: dict = Depends(get_current_user),
):
    """Registro de cada vez que un vendedor uso 'Cargar con foto' en su panel -
    para que Camilo pueda ver que se esta usando y cuanto cuesta aprox."""
    return list_ai_draft_logs(db, limit=limit)


@router.get("/comment-classifications")
def read_comment_ai_logs(
    limit: int = 100,
    store_id: int | None = None,
    db: Session = Depends(get_ai_db),
    _user: dict = Depends(get_current_user),
):
    """Registro de cada comentario del live que paso por el agente - que
    etiqueta eligio, con que proveedor, si fallo. Para monitorear en vivo que
    esta haciendo la IA."""
    query = db.query(CommentAiLog).order_by(CommentAiLog.created_at.desc())
    if store_id is not None:
        query = query.filter(CommentAiLog.store_id == store_id)
    rows = query.limit(limit).all()
    return [
        {
            "id": r.id,
            "store_id": r.store_id,
            "store_name": r.store_name,
            "username": r.username,
            "comment": r.comment,
            "ai_provider": r.ai_provider,
            "intent": r.intent,
            "label_text": r.label_text,
            "skip_response": bool(r.skip_response),
            "success": bool(r.success),
            "error_message": r.error_message,
            "prompt_tokens": r.prompt_tokens,
            "completion_tokens": r.completion_tokens,
            "estimated_cost_usd": r.estimated_cost_usd,
            "created_at": r.created_at,
        }
        for r in rows
    ]
