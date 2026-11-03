-- Frozen schema for revision 0003; legacy accounts receive an unknown random password hash.
ALTER TABLE app_user ADD COLUMN password_hash text;
ALTER TABLE app_user ADD COLUMN is_active boolean NOT NULL DEFAULT true;
ALTER TABLE app_user ADD COLUMN created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP;
ALTER TABLE app_user ADD COLUMN failed_login_count integer NOT NULL DEFAULT 0;
ALTER TABLE app_user ADD COLUMN last_failed_login_at timestamptz;
ALTER TABLE app_user ADD COLUMN locked_until timestamptz;
ALTER TABLE app_user ADD CONSTRAINT ck_user_argon2id CHECK (password_hash LIKE '$argon2id$%');
ALTER TABLE app_user ADD CONSTRAINT ck_user_failed_count CHECK (failed_login_count >= 0);


CREATE TABLE session (
	id UUID NOT NULL,
	token_hash BYTEA NOT NULL,
	user_id UUID NOT NULL,
	csrf_hash BYTEA NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	CHECK (expires_at > created_at),
	UNIQUE (token_hash),
	FOREIGN KEY(user_id) REFERENCES app_user (id)
)

;

CREATE INDEX ix_auth_session_expiry ON session (expires_at);


CREATE TABLE auth_login_attempt (
	key VARCHAR(64) NOT NULL,
	failures INTEGER NOT NULL,
	blocked_until TIMESTAMP WITH TIME ZONE,
	last_failed_login_at TIMESTAMP WITH TIME ZONE,
	PRIMARY KEY (key),
	CHECK (failures >= 0)
)

;
