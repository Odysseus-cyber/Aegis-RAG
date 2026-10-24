from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from app.telemetry import logger as tl
from app.telemetry.schema import Feedback, Message

logger = logging.getLogger(__name__)


async def record_feedback(
    *,
    message_id: str,
    rating: int,
    comment: str | None = None,
) -> str:
    """Write a feedback row to the database.

    Args:
        message_id: The assistant message this feedback is for.
        rating: 1 for thumbs up, -1 for thumbs down.
        comment: Optional free-text comment from the user.

    Returns:
        The new feedback row ID.
    """
    feedback_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    async with tl._session_factory() as session:
        message = await session.get(Message, message_id)
        if message is None or message.role != "assistant":
            raise LookupError("Assistant message not found")
        row = Feedback(
            id=feedback_id,
            message_id=message_id,
            rating=rating,
            comment=comment,
            created_at=now,
        )
        session.add(row)
        await session.commit()

    logger.debug("Feedback recorded: message_id=%s rating=%d", message_id, rating)
    return feedback_id
