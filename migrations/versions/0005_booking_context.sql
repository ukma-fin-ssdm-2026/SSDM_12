-- Infrastructure read/lock boundary. Domain decisions remain in Python.
-- VOLATILE is required: each query below gets a fresh READ COMMITTED snapshot.
CREATE FUNCTION public.booking_context(
    p_student uuid, p_slot uuid, p_now timestamptz, p_demo boolean, p_key text
)
RETURNS TABLE (authorized boolean, details jsonb, state jsonb)
LANGUAGE plpgsql VOLATILE PARALLEL UNSAFE SECURITY INVOKER
SET search_path = pg_catalog, public
AS $$
DECLARE
    actor uuid;
    slot_details jsonb;
    booking_state jsonb;
BEGIN
    PERFORM pg_advisory_xact_lock_shared(7120001);
    SELECT u.id INTO actor
    FROM public.app_user u JOIN public.user_role r ON r.user_id = u.id
    WHERE u.id = p_student AND r.role = 'student' AND (p_demo OR u.is_active)
    FOR NO KEY UPDATE OF u;
    IF NOT FOUND THEN
        RETURN QUERY SELECT false, NULL::jsonb, NULL::jsonb;
        RETURN;
    END IF;

    SELECT to_jsonb(s) || jsonb_build_object(
        'name', r.name, 'type', r.type, 'capacity', r.capacity,
        'provider_id', r.provider_id, 'full_name', u.full_name,
        'policy_id', p.id, 'booking_limit', p.booking_limit,
        'cancel_window_minutes', p.cancel_window_minutes,
        'blocked', EXISTS (
            SELECT 1 FROM public.time_block b WHERE b.resource_id = s.resource_id
            AND b.starts_at < s.ends_at AND b.ends_at > s.starts_at
        )
    ) INTO slot_details
    FROM public.slot s JOIN public.resource r ON r.id = s.resource_id
    JOIN public.app_user u ON u.id = r.provider_id
    CROSS JOIN public.current_policy cp
    JOIN public.booking_policy p ON p.id = cp.policy_id
    WHERE s.id = p_slot
    FOR NO KEY UPDATE OF s;

    -- Separate query AFTER both row-lock waits, including the idempotency winner.
    SELECT jsonb_build_object(
        'taken', EXISTS (SELECT 1 FROM public.booking b
            WHERE b.slot_id = p_slot AND b.status = 'confirmed'),
        'open_rows', (SELECT jsonb_agg(jsonb_build_array(s.starts_at, s.ends_at))
            FROM public.slot s JOIN public.booking b ON b.slot_id = s.id
            WHERE b.student_id = p_student AND b.status = 'confirmed' AND s.ends_at > p_now),
        'previous', (SELECT to_jsonb(b) FROM public.booking b
            JOIN public.idempotency i ON i.booking_id = b.id
            WHERE i.student_id = p_student AND i.key = p_key)
    ) INTO booking_state;
    RETURN QUERY SELECT true, slot_details, booking_state;
END;
$$;
REVOKE ALL ON FUNCTION public.booking_context(uuid, uuid, timestamptz, boolean, text) FROM PUBLIC;
