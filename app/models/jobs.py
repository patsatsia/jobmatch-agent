from datetime import datetime

from sqlalchemy import ARRAY, DateTime, Index, String, Text, UniqueConstraint, false
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class Job(TimestampMixin, Base):
    __tablename__ = "jobs"
    __table_args__ = (
        UniqueConstraint("source", "source_id"),
        Index("ix_jobs_tags", "tags", postgresql_using="gin"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(32))
    source_id: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    company: Mapped[str] = mapped_column(Text)
    location: Mapped[str] = mapped_column(Text, server_default="")
    url: Mapped[str] = mapped_column(Text)
    is_remote: Mapped[bool] = mapped_column(server_default=false())
    has_visa_sponsorship: Mapped[bool] = mapped_column(server_default=false())
    tags: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default="{}")
    job_types: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default="{}")
    posted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    description_html: Mapped[str] = mapped_column(Text)
    description_text: Mapped[str | None] = mapped_column(Text)

    def __repr__(self) -> str:
        return f"<Job id={self.id} {self.source}:{self.source_id} {self.title!r}>"
