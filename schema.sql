-- Safe Home CRM — PostgreSQL სქემა (Phase 1 საფუძველი)
--
-- ეს სქემა 1:1 ასახავს დღეს არსებულ 12 Google Sheets ცხრილს (იგივე
-- სვეტების სახელებით, რომ sheets_postgres.py-ს არაფრის გამოგონება არ
-- დასჭირდეს) + სამი ახალი, დამატებითი ცხრილი Phase 1-ის RBAC/Audit
-- საფუძვლისთვის.
--
-- მნიშვნელოვანი დიზაინის გადაწყვეტილება: თარიღი/დრო ველები (created_at,
-- updated_at, clock_in, clock_out და ა.შ.) ინახება TEXT ტიპად, ზუსტად
-- იმავე ფორმატით ("%Y-%m-%d %H:%M"), როგორც აქამდე Google Sheets-ში
-- ინახებოდა — რადგან არსებული კოდი ბევრგან პირდაპირ ამ სტრიქონებზე
-- აკეთებს შედარებას/parsing-ს (მაგ. `.startswith(today)`). ეს
-- გადაწყვეტილება პრიორიტეტს ანიჭებს "არაფერი არ დაირღვეს"-ს ლამაზ
-- native TIMESTAMP ტიპებზე — მომავალ ფაზაში, საჭიროების შემთხვევაში,
-- მარტივად მიგრირდება.
--
-- იდემპოტენტურია (CREATE TABLE IF NOT EXISTS) — ხელახლა გაშვება
-- უსაფრთხოა.

CREATE TABLE IF NOT EXISTS agents (
    agent_id            TEXT PRIMARY KEY,
    name                TEXT NOT NULL DEFAULT '',
    phone               TEXT NOT NULL DEFAULT '',
    telegram_username   TEXT NOT NULL DEFAULT '',
    telegram_chat_id    TEXT NOT NULL DEFAULT '',
    active              TEXT NOT NULL DEFAULT 'yes',
    registered_at       TEXT NOT NULL DEFAULT '',
    team                TEXT NOT NULL DEFAULT '',
    role                TEXT NOT NULL DEFAULT 'agent',
    internal_number     TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS tasks (
    task_id             TEXT PRIMARY KEY,
    title               TEXT NOT NULL DEFAULT '',
    description         TEXT NOT NULL DEFAULT '',
    assigned_to         TEXT NOT NULL DEFAULT '',
    status              TEXT NOT NULL DEFAULT 'New',
    priority            TEXT NOT NULL DEFAULT '',
    due_date            TEXT NOT NULL DEFAULT '',
    created_by          TEXT NOT NULL DEFAULT '',
    created_at          TEXT NOT NULL DEFAULT '',
    updated_at          TEXT NOT NULL DEFAULT '',
    notified            TEXT NOT NULL DEFAULT 'no',
    lead_type           TEXT NOT NULL DEFAULT '',
    client_phone        TEXT NOT NULL DEFAULT '',
    deal_type           TEXT NOT NULL DEFAULT '',
    listing_id          TEXT NOT NULL DEFAULT '',
    viewing_time        TEXT NOT NULL DEFAULT '',
    assigned_to_name    TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_tasks_assigned_to ON tasks (assigned_to);
CREATE INDEX IF NOT EXISTS idx_tasks_client_phone ON tasks (client_phone);

CREATE TABLE IF NOT EXISTS reports (
    report_id           TEXT PRIMARY KEY,
    agent_id            TEXT NOT NULL DEFAULT '',
    client_phone        TEXT NOT NULL DEFAULT '',
    actions             TEXT NOT NULL DEFAULT '',
    notes               TEXT NOT NULL DEFAULT '',
    file_id             TEXT NOT NULL DEFAULT '',
    created_at          TEXT NOT NULL DEFAULT '',
    agent_name          TEXT NOT NULL DEFAULT '',
    quality_auto        TEXT NOT NULL DEFAULT '',
    quality_manual      TEXT NOT NULL DEFAULT '',
    rated_by            TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_reports_agent_id ON reports (agent_id);
CREATE INDEX IF NOT EXISTS idx_reports_client_phone ON reports (client_phone);

CREATE TABLE IF NOT EXISTS dayoff (
    request_id          TEXT PRIMARY KEY,
    agent_id            TEXT NOT NULL DEFAULT '',
    date                TEXT NOT NULL DEFAULT '',
    reason              TEXT NOT NULL DEFAULT '',
    status              TEXT NOT NULL DEFAULT 'pending',
    created_at          TEXT NOT NULL DEFAULT '',
    decided_at          TEXT NOT NULL DEFAULT '',
    agent_name          TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS meetings (
    meeting_id          TEXT PRIMARY KEY,
    timestamp           TEXT NOT NULL DEFAULT '',
    owner_phone         TEXT NOT NULL DEFAULT '',
    myhome_link         TEXT NOT NULL DEFAULT '',
    myhome_id           TEXT NOT NULL DEFAULT '',
    ssge_link           TEXT NOT NULL DEFAULT '',
    ssge_id             TEXT NOT NULL DEFAULT '',
    condition           TEXT NOT NULL DEFAULT '',
    client_phone        TEXT NOT NULL DEFAULT '',
    district            TEXT NOT NULL DEFAULT '',
    address             TEXT NOT NULL DEFAULT '',
    meeting_date        TEXT NOT NULL DEFAULT '',
    agent_id            TEXT NOT NULL DEFAULT '',
    agent_name          TEXT NOT NULL DEFAULT '',
    price               TEXT NOT NULL DEFAULT '',
    percent             TEXT NOT NULL DEFAULT '',
    time                TEXT NOT NULL DEFAULT '',
    internal_number     TEXT NOT NULL DEFAULT '',
    agent_phone         TEXT NOT NULL DEFAULT '',
    team_leader         TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_meetings_agent_id ON meetings (agent_id);
CREATE INDEX IF NOT EXISTS idx_meetings_client_phone ON meetings (client_phone);

CREATE TABLE IF NOT EXISTS schedule (
    agent_id            TEXT PRIMARY KEY,
    mon TEXT NOT NULL DEFAULT 'off',
    tue TEXT NOT NULL DEFAULT 'off',
    wed TEXT NOT NULL DEFAULT 'off',
    thu TEXT NOT NULL DEFAULT 'off',
    fri TEXT NOT NULL DEFAULT 'off',
    sat TEXT NOT NULL DEFAULT 'off',
    sun TEXT NOT NULL DEFAULT 'off',
    updated_at          TEXT NOT NULL DEFAULT '',
    agent_name          TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS attendance (
    attendance_id       TEXT PRIMARY KEY,
    agent_id            TEXT NOT NULL DEFAULT '',
    date                TEXT NOT NULL DEFAULT '',
    mode                TEXT NOT NULL DEFAULT '',
    clock_in            TEXT NOT NULL DEFAULT '',
    clock_out           TEXT NOT NULL DEFAULT '',
    count_submitted     TEXT NOT NULL DEFAULT '',
    agent_name          TEXT NOT NULL DEFAULT '',
    site_count          TEXT NOT NULL DEFAULT '',
    myhome_count        TEXT NOT NULL DEFAULT '',
    ssge_count          TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_attendance_agent_date ON attendance (agent_id, date);

CREATE TABLE IF NOT EXISTS warnings (
    warning_id          TEXT PRIMARY KEY,
    agent_id            TEXT NOT NULL DEFAULT '',
    type                TEXT NOT NULL DEFAULT '',
    detail              TEXT NOT NULL DEFAULT '',
    created_at          TEXT NOT NULL DEFAULT '',
    agent_name          TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_warnings_agent_id ON warnings (agent_id);

CREATE TABLE IF NOT EXISTS shift_swaps (
    swap_id             TEXT PRIMARY KEY,
    agent_id            TEXT NOT NULL DEFAULT '',
    agent_name          TEXT NOT NULL DEFAULT '',
    request_type        TEXT NOT NULL DEFAULT '',
    from_mode           TEXT NOT NULL DEFAULT '',
    to_mode             TEXT NOT NULL DEFAULT '',
    target_agent_id     TEXT NOT NULL DEFAULT '',
    target_agent_name   TEXT NOT NULL DEFAULT '',
    swap_date           TEXT NOT NULL DEFAULT '',
    note                TEXT NOT NULL DEFAULT '',
    status              TEXT NOT NULL DEFAULT '',
    accepted_by         TEXT NOT NULL DEFAULT '',
    accepted_by_name    TEXT NOT NULL DEFAULT '',
    created_at          TEXT NOT NULL DEFAULT '',
    decided_at          TEXT NOT NULL DEFAULT '',
    decided_by          TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_shift_swaps_agent_id ON shift_swaps (agent_id);

CREATE TABLE IF NOT EXISTS exclusives (
    exclusive_id        TEXT PRIMARY KEY,
    agent_id            TEXT NOT NULL DEFAULT '',
    agent_name          TEXT NOT NULL DEFAULT '',
    contact_internal    TEXT NOT NULL DEFAULT '',
    owner_phone         TEXT NOT NULL DEFAULT '',
    property_type       TEXT NOT NULL DEFAULT '',
    deal_type           TEXT NOT NULL DEFAULT '',
    building_status     TEXT NOT NULL DEFAULT '',
    condition           TEXT NOT NULL DEFAULT '',
    location            TEXT NOT NULL DEFAULT '',
    cadastral_code      TEXT NOT NULL DEFAULT '',
    area                TEXT NOT NULL DEFAULT '',
    rooms               TEXT NOT NULL DEFAULT '',
    bedrooms            TEXT NOT NULL DEFAULT '',
    floors_total        TEXT NOT NULL DEFAULT '',
    floor_number        TEXT NOT NULL DEFAULT '',
    project_type        TEXT NOT NULL DEFAULT '',
    bathrooms           TEXT NOT NULL DEFAULT '',
    balcony             TEXT NOT NULL DEFAULT '',
    price               TEXT NOT NULL DEFAULT '',
    percent             TEXT NOT NULL DEFAULT '',
    notes               TEXT NOT NULL DEFAULT '',
    photos              TEXT NOT NULL DEFAULT '',
    status              TEXT NOT NULL DEFAULT 'active',
    created_at          TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_exclusives_agent_id ON exclusives (agent_id);

CREATE TABLE IF NOT EXISTS questions (
    question_id         TEXT PRIMARY KEY,
    agent_id            TEXT NOT NULL DEFAULT '',
    agent_name          TEXT NOT NULL DEFAULT '',
    team                TEXT NOT NULL DEFAULT '',
    text                TEXT NOT NULL DEFAULT '',
    status              TEXT NOT NULL DEFAULT 'open',
    answer              TEXT NOT NULL DEFAULT '',
    answered_by         TEXT NOT NULL DEFAULT '',
    created_at          TEXT NOT NULL DEFAULT '',
    answered_at         TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS exclusive_shares (
    share_id            TEXT PRIMARY KEY,
    exclusive_id        TEXT NOT NULL DEFAULT '',
    from_agent_id       TEXT NOT NULL DEFAULT '',
    from_agent_name     TEXT NOT NULL DEFAULT '',
    to_agent_id         TEXT NOT NULL DEFAULT '',
    to_agent_name       TEXT NOT NULL DEFAULT '',
    note                TEXT NOT NULL DEFAULT '',
    created_at          TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_exclusive_shares_exclusive_id ON exclusive_shares (exclusive_id);

-- =====================================================================
-- Phase 1 დამატება: RBAC + Audit Log საფუძველი.
--
-- ეს ცხრილები ᲐᲠ ცვლის დღევანდელ ავტორიზაციის ლოგიკას (ADMIN_CHAT_IDS
-- env-ცვლადი, agents.role == 'team_lead') — ისინი ჯერჯერობით მხოლოდ
-- ინფრასტრუქტურული საფუძველია მომავალი ფაზებისთვის (Mini App-ის
-- დახვეწილი RBAC, permission-based AI tool-calls). დღეს მხოლოდ
-- audit_log ივსება რეალურად, რამდენიმე მაღალი რისკის მოქმედებაზე
-- (იხ. sheets_postgres.py-ს `_audit(...)` გამოძახებები).
-- =====================================================================

CREATE TABLE IF NOT EXISTS roles (
    role_key            TEXT PRIMARY KEY,
    description         TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS permissions (
    permission_key      TEXT PRIMARY KEY,
    description         TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS role_permissions (
    role_key            TEXT NOT NULL REFERENCES roles(role_key) ON DELETE CASCADE,
    permission_key      TEXT NOT NULL REFERENCES permissions(permission_key) ON DELETE CASCADE,
    PRIMARY KEY (role_key, permission_key)
);

INSERT INTO roles (role_key, description) VALUES
    ('admin',     'ADMIN_CHAT_IDS — სრული წვდომა (დღეს env-ით მართული)'),
    ('team_lead', 'თიმლიდერი — საკუთარი გუნდის ხედვა/დამტკიცებები'),
    ('agent',     'რიგითი აგენტი — მხოლოდ საკუთარი მონაცემები')
ON CONFLICT (role_key) DO NOTHING;

INSERT INTO permissions (permission_key, description) VALUES
    ('view_own_dashboard',      'საკუთარი დღის/დავალებების ნახვა'),
    ('view_team_dashboard',     'გუნდის დაშბორდის ნახვა'),
    ('view_company_dashboard',  'მთელი კომპანიის დაშბორდის ნახვა'),
    ('decide_dayoff',           'დასვენების მოთხოვნის დამტკიცება/უარყოფა'),
    ('decide_shift_swap',       'ცვლის გაცვლის საბოლოო დამტკიცება'),
    ('manage_agents',           'აგენტის დამატება/გუნდის-როლის შეცვლა/დეაქტივაცია'),
    ('rate_reports',            'აგენტის რეპორტის ხელით შეფასება')
ON CONFLICT (permission_key) DO NOTHING;

INSERT INTO role_permissions (role_key, permission_key) VALUES
    ('agent', 'view_own_dashboard'),
    ('team_lead', 'view_own_dashboard'),
    ('team_lead', 'view_team_dashboard'),
    ('team_lead', 'decide_dayoff'),
    ('team_lead', 'decide_shift_swap'),
    ('team_lead', 'rate_reports'),
    ('admin', 'view_own_dashboard'),
    ('admin', 'view_team_dashboard'),
    ('admin', 'view_company_dashboard'),
    ('admin', 'decide_dayoff'),
    ('admin', 'decide_shift_swap'),
    ('admin', 'manage_agents'),
    ('admin', 'rate_reports')
ON CONFLICT DO NOTHING;

CREATE TABLE IF NOT EXISTS audit_log (
    id                  BIGSERIAL PRIMARY KEY,
    occurred_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    actor_agent_id      TEXT NOT NULL DEFAULT '',
    actor_label         TEXT NOT NULL DEFAULT '',
    action              TEXT NOT NULL,
    entity_type         TEXT NOT NULL DEFAULT '',
    entity_id           TEXT NOT NULL DEFAULT '',
    old_value           JSONB,
    new_value           JSONB,
    source              TEXT NOT NULL DEFAULT 'bot'
);
CREATE INDEX IF NOT EXISTS idx_audit_log_entity ON audit_log (entity_type, entity_id);
CREATE INDEX IF NOT EXISTS idx_audit_log_occurred_at ON audit_log (occurred_at);

-- იმ Postgres როლისთვის, რომლითაც აპლიკაცია უკავშირდება ბაზას,
-- დამატებით (არააუცილებელი, მაგრამ რეკომენდებული) — audit_log
-- ცხრილის ნამდვილი უცვლელობისთვის: მოცემული აპლიკაციის db user-ს
-- REVOKE UPDATE, DELETE ON audit_log — ეს ხელით სრულდება production
-- ბაზაზე, README.md-ში აღწერილია.
