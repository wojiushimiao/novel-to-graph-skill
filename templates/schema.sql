-- ============================================================
-- novel-analysis-skill · 数据库 DDL 模板 (v0.4.0)
-- 锚定: L3_接口契约与约束.md §二·数据库Schema契约
--       InkForge ddl.py + 历史信息统合数据库规范 v2.1
-- 适用: SQLite 3.35+
-- ============================================================

-- 实体档案表
CREATE TABLE IF NOT EXISTS entities (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    type TEXT NOT NULL CHECK(type IN (
        'character','location','event','item','rule','system','monster','knowledge','E_module'
    )),
    base_info TEXT DEFAULT '{}',      -- JSON: {name, aliases, first_appearance, entity_description}
    detail_info TEXT DEFAULT '{}',    -- JSON: {attributes, relationships_summary, character_arc}
    stitch_tags TEXT DEFAULT '{}',    -- JSON: {sigma, epsilon, kappa}
    coords TEXT DEFAULT '{}',         -- JSON: {T, L, C, E, R} 五维唯一值（v0.4.0 移除 K）
    info TEXT DEFAULT '',             -- 实体详情（500-1500字 LLM 语义提炼，v0.4.0 新增）
    importance_score REAL DEFAULT 0.0, -- 数值化重要度 (0.0-1.0)
    source_chapter TEXT DEFAULT '',
    char_offset INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

-- wiki 关系表（有向图边）
-- 关系类型：轴关系模型 v0.4.0（6种轴关系）+ 旧关系类型（向后兼容，S6.1 会转换为轴关系）
CREATE TABLE IF NOT EXISTS wiki_relations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id TEXT NOT NULL REFERENCES entities(id),
    target_id TEXT NOT NULL REFERENCES entities(id),
    relation_type TEXT NOT NULL CHECK(relation_type IN (
        -- 轴关系类型 v0.4.0
        'T_main','T_branch','S_topo','A_causal','A_arc','R_strong',
        -- 旧关系类型（向后兼容）
        'located_in','participates_in','relates_to',
        'evolves_to','causes','belongs_to','references'
    )),
    strength TEXT NOT NULL DEFAULT 'weak' CHECK(strength IN ('strong','weak')),
    description TEXT DEFAULT '',
    source_chapter TEXT DEFAULT '',
    created_at TEXT DEFAULT (datetime('now'))
);

-- 时间线索引表
CREATE TABLE IF NOT EXISTS timeline_index (
    id TEXT PRIMARY KEY,                -- T{n}_阶段名
    name TEXT NOT NULL,
    time_range TEXT DEFAULT '',
    description TEXT DEFAULT '',
    location_ids TEXT DEFAULT '[]',     -- JSON array
    character_ids TEXT DEFAULT '[]',    -- JSON array
    event_ids TEXT DEFAULT '[]',        -- JSON array
    theme_ids TEXT DEFAULT '[]',        -- JSON array
    rule_ids TEXT DEFAULT '[]',         -- JSON array
    tone TEXT DEFAULT ''
);

-- 事件档案表
CREATE TABLE IF NOT EXISTS events (
    id TEXT PRIMARY KEY,                -- E_事件名
    name TEXT NOT NULL,
    timeline_id TEXT REFERENCES timeline_index(id),
    event_type TEXT DEFAULT 'plot' CHECK(event_type IN (
        'plot','character','world','daily'
    )),
    description TEXT DEFAULT '',
    location_ids TEXT DEFAULT '[]',     -- JSON array
    character_ids TEXT DEFAULT '[]',    -- JSON array
    theme_ids TEXT DEFAULT '[]',        -- JSON array
    rule_ids TEXT DEFAULT '[]',         -- JSON array
    character_reactions TEXT DEFAULT '{}',  -- JSON
    subsequent_effects TEXT DEFAULT '{}',   -- JSON
    wiki_relations TEXT DEFAULT '[]',       -- JSON
    coords TEXT DEFAULT '{}'                 -- JSON
);

-- 主题聚类表
CREATE TABLE IF NOT EXISTS theme_clusters (
    id TEXT PRIMARY KEY,                -- K_主题名
    name TEXT NOT NULL,
    description TEXT DEFAULT '',
    related_entity_ids TEXT DEFAULT '[]',   -- JSON array
    related_theme_ids TEXT DEFAULT '[]',    -- JSON array
    wiki_relations TEXT DEFAULT '[]',       -- JSON
    coords TEXT DEFAULT '{}'                -- JSON
);

-- 规则档案表
CREATE TABLE IF NOT EXISTS rules (
    id TEXT PRIMARY KEY,                -- R_{子类}_规则名
    name TEXT NOT NULL,
    rule_type TEXT NOT NULL CHECK(rule_type IN (
        'R_power','R_philosophy','R_cultivation',
        'R_energy_tech','R_law','R_system'
    )),
    scope TEXT DEFAULT '',
    content TEXT DEFAULT '[]',          -- JSON: 规则条款列表
    exceptions TEXT DEFAULT '',
    related_entity_ids TEXT DEFAULT '[]',   -- JSON array
    version INTEGER DEFAULT 1,
    overwrite_history TEXT DEFAULT '[]',    -- JSON
    narrative_impact TEXT DEFAULT '',
    coords TEXT DEFAULT '{}'                -- JSON
);

-- ============================================================
-- 索引
-- ============================================================

CREATE INDEX IF NOT EXISTS idx_entities_type ON entities(type);
CREATE INDEX IF NOT EXISTS idx_entities_name ON entities(name);
CREATE INDEX IF NOT EXISTS idx_entities_importance ON entities(importance_score);
CREATE INDEX IF NOT EXISTS idx_relations_source ON wiki_relations(source_id);
CREATE INDEX IF NOT EXISTS idx_relations_target ON wiki_relations(target_id);
CREATE INDEX IF NOT EXISTS idx_relations_type ON wiki_relations(relation_type);
CREATE INDEX IF NOT EXISTS idx_relations_strength ON wiki_relations(strength);
CREATE INDEX IF NOT EXISTS idx_events_timeline ON events(timeline_id);
CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type);
CREATE INDEX IF NOT EXISTS idx_timeline_name ON timeline_index(name);
CREATE INDEX IF NOT EXISTS idx_rules_type ON rules(rule_type);
CREATE INDEX IF NOT EXISTS idx_themes_name ON theme_clusters(name);

-- ============================================================
-- 常用查询视图
-- ============================================================

-- 角色关系密度视图
CREATE VIEW IF NOT EXISTS v_character_relations AS
SELECT
    c1.name AS source_name,
    c2.name AS target_name,
    wr.relation_type,
    wr.strength,
    wr.description
FROM wiki_relations wr
JOIN entities c1 ON wr.source_id = c1.id
JOIN entities c2 ON wr.target_id = c2.id
WHERE c1.type = 'character' AND c2.type = 'character';

-- 角色-地点关系视图
CREATE VIEW IF NOT EXISTS v_character_locations AS
SELECT
    c.name AS character_name,
    l.name AS location_name,
    wr.relation_type,
    wr.strength
FROM wiki_relations wr
JOIN entities c ON wr.source_id = c.id AND c.type = 'character'
JOIN entities l ON wr.target_id = l.id AND l.type = 'location';

-- 事件参与视图
CREATE VIEW IF NOT EXISTS v_event_participants AS
SELECT
    e.name AS event_name,
    e.event_type,
    c.name AS participant_name,
    wr.relation_type,
    wr.strength
FROM wiki_relations wr
JOIN entities e ON wr.target_id = e.id AND e.type = 'event'
JOIN entities c ON wr.source_id = c.id AND c.type = 'character';
