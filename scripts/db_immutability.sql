-- Phase 3: Audit log immutability hardening
-- Run once as healthcare_user (or any DB superuser) after initial deployment.
--
-- Uses two complementary layers:
--   1. REVOKE UPDATE/DELETE + RLS policies — blocks non-superuser app roles
--   2. BEFORE UPDATE/DELETE triggers — blocks all users including superusers
--
-- After applying, verify with:
--   UPDATE audit_logs SET query_hash='test' WHERE ...;   -- must raise exception
--   DELETE FROM audit_logs WHERE ...;                     -- must raise exception
--   INSERT INTO audit_logs (...) VALUES (...);            -- must succeed

-- Layer 1: privilege revocation
REVOKE UPDATE, DELETE ON audit_logs FROM healthcare_user;
GRANT INSERT ON audit_logs TO healthcare_user;

-- Layer 1b: row-level security (also applies when separate app role is used)
ALTER TABLE audit_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_logs FORCE ROW LEVEL SECURITY;

CREATE POLICY no_update_audit ON audit_logs FOR UPDATE USING (FALSE);
CREATE POLICY no_delete_audit ON audit_logs FOR DELETE USING (FALSE);

-- Layer 2: trigger-based guard (blocks all users, including superusers)
CREATE OR REPLACE FUNCTION audit_log_immutability_guard()
RETURNS TRIGGER AS $func$
BEGIN
    RAISE EXCEPTION
        'audit_logs is append-only: operations are not permitted (HIPAA compliance)';
END;
$func$ LANGUAGE plpgsql;

CREATE TRIGGER audit_log_no_update
    BEFORE UPDATE ON audit_logs
    FOR EACH ROW EXECUTE FUNCTION audit_log_immutability_guard();

CREATE TRIGGER audit_log_no_delete
    BEFORE DELETE ON audit_logs
    FOR EACH ROW EXECUTE FUNCTION audit_log_immutability_guard();
