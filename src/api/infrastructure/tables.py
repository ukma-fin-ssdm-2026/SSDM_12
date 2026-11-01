"""PostgreSQL schema для поточних сценаріїв; створюється лише міграцією Alembic."""

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Identity,
    Index,
    Integer,
    LargeBinary,
    MetaData,
    String,
    Table,
    Text,
    Time,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID, ExcludeConstraint

metadata = MetaData()

users = Table(
    "app_user",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("full_name", Text, nullable=False),
    Column("email", Text, nullable=False),
    Column("password_hash", Text, nullable=False),
    Column("is_active", Boolean, nullable=False, server_default=text("true")),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("failed_login_count", Integer, nullable=False, server_default=text("0")),
    Column("last_failed_login_at", DateTime(timezone=True)),
    Column("locked_until", DateTime(timezone=True)),
    CheckConstraint("password_hash LIKE '$argon2id$%'"),
    CheckConstraint("failed_login_count >= 0"),
)
Index("uq_user_email_lower", func.lower(users.c.email), unique=True)
roles = Table(
    "user_role",
    metadata,
    Column("user_id", UUID(as_uuid=True), ForeignKey("app_user.id"), primary_key=True),
    Column("role", String(16), primary_key=True),
    CheckConstraint("role IN ('student','provider','admin')"),
)
resources = Table(
    "resource",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("name", Text, nullable=False),
    Column("type", String(16), nullable=False),
    Column("capacity", Integer),
    Column("provider_id", UUID(as_uuid=True), nullable=False),
    Column("provider_role", String(16), nullable=False, server_default="provider"),
    CheckConstraint("provider_role = 'provider'"),
    CheckConstraint(
        "(type='room' AND capacity IS NOT NULL AND capacity BETWEEN 1 AND 1000) OR (type='consultation' AND capacity IS NULL)"
    ),
    ForeignKeyConstraint(
        ["provider_id", "provider_role"],
        ["user_role.user_id", "user_role.role"],
        deferrable=True,
        initially="DEFERRED",
    ),
)
templates = Table(
    "availability_template",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("resource_id", UUID(as_uuid=True), ForeignKey("resource.id"), nullable=False),
    Column("weekday", Integer, nullable=False),
    Column("start_local", Time, nullable=False),
    Column("end_local", Time, nullable=False),
    Column("slot_minutes", Integer, nullable=False),
    Column("valid_from", Date, nullable=False),
    Column("valid_to", Date),
    CheckConstraint("weekday BETWEEN 1 AND 7 AND end_local > start_local AND slot_minutes > 0"),
    CheckConstraint("valid_to IS NULL OR valid_to >= valid_from"),
)
policies = Table(
    "booking_policy",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("booking_limit", Integer, nullable=False),
    Column("cancel_window_minutes", Integer, nullable=False),
    CheckConstraint("booking_limit > 0 AND cancel_window_minutes >= 0"),
)
current_policy = Table(
    "current_policy",
    metadata,
    Column("singleton", Integer, primary_key=True),
    Column("policy_id", UUID(as_uuid=True), ForeignKey("booking_policy.id"), nullable=False),
    CheckConstraint("singleton=1"),
)
slots = Table(
    "slot",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("resource_id", UUID(as_uuid=True), ForeignKey("resource.id"), nullable=False),
    Column("template_id", UUID(as_uuid=True), ForeignKey("availability_template.id")),
    Column("starts_at", DateTime(timezone=True), nullable=False),
    Column("ends_at", DateTime(timezone=True), nullable=False),
    Column("is_active", Boolean, nullable=False, server_default=text("true")),
    CheckConstraint("ends_at > starts_at"),
)
slots.append_constraint(
    ExcludeConstraint(
        (slots.c.resource_id, "="),
        (func.tstzrange(slots.c.starts_at, slots.c.ends_at, "[)"), "&&"),
        name="ex_slot_active_overlap",
        using="gist",
        where=slots.c.is_active,
        deferrable=True,
        initially="DEFERRED",
    )
)
blocks = Table(
    "time_block",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("resource_id", UUID(as_uuid=True), ForeignKey("resource.id"), nullable=False),
    Column("starts_at", DateTime(timezone=True), nullable=False),
    Column("ends_at", DateTime(timezone=True), nullable=False),
    Column("reason", Text, nullable=False),
    CheckConstraint("ends_at > starts_at AND length(trim(reason)) > 0"),
)
bookings = Table(
    "booking",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("slot_id", UUID(as_uuid=True), ForeignKey("slot.id"), nullable=False),
    Column("student_id", UUID(as_uuid=True), ForeignKey("app_user.id"), nullable=False),
    Column("status", String(16), nullable=False),
    Column("policy_id", UUID(as_uuid=True), ForeignKey("booking_policy.id"), nullable=False),
    Column("cancel_deadline_at", DateTime(timezone=True), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("cancelled_at", DateTime(timezone=True)),
    Column("cancelled_by", UUID(as_uuid=True), ForeignKey("app_user.id")),
    Column("cancellation_kind", String(32)),
    Column("cancellation_reason", Text),
    Column(
        "rescheduled_to_id",
        UUID(as_uuid=True),
        ForeignKey("booking.id", deferrable=True, initially="DEFERRED"),
    ),
    UniqueConstraint("rescheduled_to_id"),
    CheckConstraint("status IN ('confirmed','cancelled')"),
    CheckConstraint(
        "(cancellation_kind IS NOT DISTINCT FROM 'rescheduled') = (rescheduled_to_id IS NOT NULL)"
    ),
    CheckConstraint(
        "status <> 'cancelled' OR (cancelled_at IS NOT NULL AND cancelled_by IS NOT NULL AND cancellation_kind IS NOT NULL)"
    ),
    CheckConstraint(
        "cancellation_kind IS NULL OR cancellation_kind IN ('student','provider_block','rescheduled')"
    ),
    CheckConstraint(
        "cancellation_kind <> 'provider_block' OR (cancellation_reason IS NOT NULL AND length(trim(cancellation_reason)) > 0)"
    ),
)
Index(
    "uq_booking_slot_confirmed",
    bookings.c.slot_id,
    unique=True,
    postgresql_where=bookings.c.status == "confirmed",
)
idempotency = Table(
    "idempotency",
    metadata,
    Column("student_id", UUID(as_uuid=True), ForeignKey("app_user.id"), primary_key=True),
    Column("key", String(64), primary_key=True),
    Column("slot_id", UUID(as_uuid=True), ForeignKey("slot.id"), nullable=False),
    Column("booking_id", UUID(as_uuid=True), ForeignKey("booking.id"), nullable=False),
)
notifications = Table(
    "notification",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("booking_id", UUID(as_uuid=True), ForeignKey("booking.id"), nullable=False),
    Column("recipient_id", UUID(as_uuid=True), ForeignKey("app_user.id"), nullable=False),
    Column("kind", String(32), nullable=False),
    Column("payload", JSONB, nullable=False),
    Column("scheduled_for", DateTime(timezone=True), nullable=False),
    Column("status", String(16), nullable=False),
    Column("attempts", Integer, nullable=False),
    Column("locked_until", DateTime(timezone=True)),
    Column("claim_token", UUID(as_uuid=True)),
    Column("sent_at", DateTime(timezone=True)),
    Column("last_error", String(64)),
    Column("next_attempt_at", DateTime(timezone=True)),
    CheckConstraint(
        "status IN ('pending','sending','sent','failed','cancelled') AND attempts >= 0"
    ),
)
Index("ix_notification_due", notifications.c.status, notifications.c.scheduled_for)
deliveries = Table(
    "notification_delivery",
    metadata,
    Column("id", UUID(as_uuid=True), ForeignKey("notification.id"), primary_key=True),
    Column("recipient_id", UUID(as_uuid=True), ForeignKey("app_user.id"), nullable=False),
    Column("kind", String(32), nullable=False),
    Column("payload", JSONB, nullable=False),
    Column("delivered_at", DateTime(timezone=True), nullable=False),
)
audit = Table(
    "audit_log",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("seq", BigInteger, Identity(), nullable=False, unique=True),
    Column("actor_id", UUID(as_uuid=True), ForeignKey("app_user.id"), nullable=False),
    Column("action", Text, nullable=False),
    Column("object_id", UUID(as_uuid=True)),
    Column("before", JSONB),
    Column("after", JSONB),
    Column("at", DateTime(timezone=True), nullable=False),
)

MUTABLE = (
    users,
    roles,
    resources,
    templates,
    policies,
    current_policy,
    slots,
    blocks,
    bookings,
    idempotency,
    notifications,
)

sessions = Table(
    "session",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("token_hash", LargeBinary, unique=True, nullable=False),
    Column("user_id", UUID(as_uuid=True), ForeignKey("app_user.id"), nullable=False),
    Column("csrf_hash", LargeBinary, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    CheckConstraint("expires_at > created_at"),
)
Index("ix_auth_session_expiry", sessions.c.expires_at)
login_attempts = Table(
    "auth_login_attempt",
    metadata,
    Column("key", String(64), primary_key=True),
    Column("failures", Integer, nullable=False),
    Column("blocked_until", DateTime(timezone=True)),
    Column("last_failed_login_at", DateTime(timezone=True)),
    CheckConstraint("failures >= 0"),
)
MUTABLE += (sessions, login_attempts)

maintenance = Table(
    "maintenance_checkpoint",
    metadata,
    Column("name", Text, primary_key=True),
    Column("completed_at", DateTime(timezone=True), nullable=False),
)
MUTABLE += (maintenance,)
