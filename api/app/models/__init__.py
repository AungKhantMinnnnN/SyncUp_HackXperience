"""Import every model file before Base.metadata is read, or Alembic autogenerate
will propose dropping the tables it cannot see."""

from app.models.base import Base
from app.models import org, scheduling, resources, finance  # noqa: F401,E402

__all__ = ["Base"]
