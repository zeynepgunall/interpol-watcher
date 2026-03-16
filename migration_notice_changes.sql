-- notice_changes tablosu migration
-- PostgreSQL'de çalıştır:
-- docker exec -it interpol_postgres psql -U interpol -d interpol_db -f /tmp/migration_notice_changes.sql

CREATE TABLE IF NOT EXISTS notice_changes (
    id         SERIAL PRIMARY KEY,
    entity_id  VARCHAR(255) NOT NULL REFERENCES notices(entity_id) ON DELETE CASCADE,
    field_name VARCHAR(100) NOT NULL,
    old_value  TEXT,
    new_value  TEXT,
    changed_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_notice_changes_entity_id ON notice_changes (entity_id);
CREATE INDEX IF NOT EXISTS ix_notice_changes_changed_at ON notice_changes (changed_at);
