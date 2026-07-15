#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""novel-to-graph-skill · T-E1 端到端管线集成测试

锚定: track_E_plan.md §T-E1
检查点:
  - CP-E1.1: 端到端管线 S1→S2.5→S3→S4→S5→S6→S7 通过
  - CP-E1.2: 五维坐标唯一值校验通过
  - CP-E1.3: info 字数达标率 >80%
  - CP-E1.4: 关系 description 均 ≤100字

测试策略:
  skill 工具不调用 LLM，所有 LLM 产出由 mock fixture 模拟。
  测试覆盖 v0.4.0 全部 5 轨道产出物的协同工作：
    - Track A: E_module 类型 + 五维坐标 + 7 校验函数 + schema.sql
    - Track B: chapter_title_sampler + timeline_skeleton_builder
    - Track C: coords_migrator + info_compressor
    - Track D: Prompt 文档（由 mock 产出体现）
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# ─── 导入路径设置 ───────────────────────────────────────────
# novel-to-graph-skill 目录名含连字符，无法作为 Python 包；
# 同时 pytest 的 pythonpath 配置 (06_核心代码) 存在冲突的 tools 包，
# 需清理 sys.modules 中 tools 相关缓存，并强制把 SKILL_DIR 放到
# sys.path 最前面，确保 tools 解析到本技能的 tools 目录。
for _mod in list(sys.modules):
    if _mod == "tools" or _mod.startswith("tools."):
        del sys.modules[_mod]

_SKILL_DIR = Path(__file__).resolve().parent.parent
if str(_SKILL_DIR) in sys.path:
    sys.path.remove(str(_SKILL_DIR))
sys.path.insert(0, str(_SKILL_DIR))

from tools.models import (  # noqa: E402
    Chunk,
    Entity,
    Relation,
    ENTITY_TYPES,
    COORD_DIMENSIONS,
    ENTITY_OUT_EDGE_LIMITS,
)
from tools.text_chunker import chunk_text  # noqa: E402
from tools.chapter_title_sampler import sample_chapter_titles  # noqa: E402
from tools.timeline_skeleton_builder import build_skeleton  # noqa: E402
from tools.schema_validator import (  # noqa: E402
    validate_coords_unique,
    validate_no_K_dimension,
    validate_info_length,
    validate_E_module_relation,
    validate_relation_desc_length,
    validate_info_cohesion,
    validate_S_topo_bidirectional,
)
from tools.coords_migrator import migrate_coords  # noqa: E402
from tools.info_compressor import (  # noqa: E402
    compress_info,
    compress_info_with_retry,
    validate_compressed_info,
    truncate_info,
    InfoTooShortError,
)


# ═══════════════════════════════════════════════════════════
# 测试数据：~5000 字小型小说样本
# ═══════════════════════════════════════════════════════════

_SAMPLE_NOVEL = """\
第一章 觉醒

清晨的阳光穿透薄雾，洒在青云城外的练武场上。少年林轩站在石台之上，双目紧闭，周身灵气如潮水般涌动。今天是青云宗一年一度的灵根测试日，所有十五岁的少年都必须参加。

林轩出身寒微，父亲是城中的铁匠，母亲早逝。他自幼体弱，被同侪嘲笑为"废材"。然而他内心坚韧，每日苦修不辍，只为今日能觉醒灵根，踏入修仙之路。

"下一个，林轩！"测灵长老的声音如同洪钟。林轩深吸一口气，将手按在测灵石上。刹那间，测灵石爆发出耀眼的金色光芒，整座练武场都被照亮。

"金灵根！竟然是罕见的金灵根！"测灵长老惊呼。人群中响起一片哗然，金灵根百年难遇，乃是剑修的绝佳资质。林轩睁开眼，嘴角微微上扬，多年的苦修终于有了回报。

第二章 拜入宗门

三日后，林轩跟随青云宗的接引弟子来到了青云山。青云宗坐落于苍莽山脉之巅，云雾缭绕间，殿宇楼阁若隐若现，宛如仙境。

"林轩，你被分配到剑峰，由赵长老亲自指导。"接引弟子递过一枚玉牌。剑峰是青云宗十二峰之一，以剑修闻名，赵长老更是宗门三大剑修之一。

剑峰后山，赵长老白发苍苍，目光如炬。他打量着林轩，缓缓说道："金灵根虽好，但剑道一途，重在心境。你可愿意吃苦？"

林轩跪地叩首："弟子愿吃苦，百死不悔。"

赵长老微微颔首，递过一柄生锈的铁剑："从今日起，每日挥剑一万次，持续三年。这是剑修的筑基功夫，不可懈怠。"

林轩接过铁剑，虽锈迹斑斑，却感到一股沉甸甸的分量。他知道，这是他剑道的起点。

第三章 初遇对手

时光荏苒，三年已过。林轩每日挥剑一万次，风雨无阻。铁剑已被他磨得雪亮，剑意初成。

这一年，青云宗举办内门弟子比武大会。林轩作为剑峰代表参赛，首轮对手是来自丹峰的萧云。

萧云出身世家，修为已至练气九层，是本届比武的热门人选。他看着林轩手中的铁剑，嗤笑道："一个铁匠的儿子，也配握剑？"

林轩不语，只是静静举剑。比试开始，萧云率先出手，一道火球呼啸而来。林轩身形一闪，铁剑横扫，剑气如虹，竟将火球一分为二。

"什么？！"萧云大惊。林轩不给他喘息之机，剑随身走，三招之内已到萧云面前。铁剑停在萧云咽喉前寸许，胜负已分。

"你……你是什么修为？"萧云颤抖着问。

"练气七层。"林轩收剑转身。全场哗然，练气七层击败练气九层，这在青云宗历史上前所未有。

第四章 秘境历练

比武大会后，林轩声名鹊起。宗门长老决定派他参加百年一次的天玄秘境历练。天玄秘境乃是上古大能留下的遗迹，内藏无数珍宝，也危机四伏。

林轩与同门师姐苏瑶结伴进入秘境。苏瑶精通阵法，性情冷淡，却对林轩颇为照拂。二人深入秘境，遭遇了一头上古凶兽——赤焰狮。

赤焰狮浑身浴火，咆哮声震耳欲聋。林轩拔剑迎敌，金灵根的剑气与狮火相撞，爆发出惊天动地的光芒。苏瑶趁机布下困阵，将赤焰狮困住。

"林轩，用你的金灵根本源之力，激发阵法！"苏瑶喝道。林轩毫不犹豫，将金灵根之力注入阵眼。阵法金光大盛，赤焰狮被困得动弹不得。

二人合力击退赤焰狮，在其巢穴中发现了一柄古剑——天玄剑。剑身铭刻着上古符文，散发着幽幽金光。林轩握住天玄剑，感到一股血脉相连的亲切感。

"此剑与你金灵根相合，算是缘分。"苏瑶淡淡说道。林轩点头，将天玄剑收入剑鞘。他知道，这柄剑将成为他剑道的重要伙伴。

第五章 魔道来袭

历练归来，林轩修为突飞猛进，已至筑基初期。然而平静的日子没有持续太久。一月之夜，魔道突袭青云宗，黑云压城，杀声震天。

为首的魔修名为血煞，修为高深，手持血色长刀，所过之处生灵涂炭。青云宗弟子死伤惨重，赵长老为保护弟子，与血煞激战，不幸身负重伤。

"师父！"林轩目眦欲裂。他拔出天玄剑，金灵根全力催动，剑身爆发万丈金光。

"小子，找死！"血煞一刀劈来，血色刀气撕裂夜空。林轩不退反进，天玄剑划出一道完美的弧线，金光与血气碰撞，方圆百丈化为废墟。

这一战，林轩以筑基初期之境，力抗魔道高手。最终，在宗门援军到来之际，血煞负伤遁走。林轩虽也身受重伤，却保住了青云宗。

经此一役，林轩名震天下。赵长老伤愈后，将剑峰掌教之位传于林轩。林轩站在剑峰之巅，望着云海翻涌，心中暗誓：必斩尽魔道，还世间太平。
"""


# ═══════════════════════════════════════════════════════════
# Mock 数据：模拟 LLM 在 S2.5/S3 阶段的产出
# ═══════════════════════════════════════════════════════════

# S2.5 阶段 LLM 产出的剧情模块（5 个，覆盖 5 章）
_MOCK_PLOT_MODULES = [
    {
        "name": "觉醒篇",
        "chapter_range": [1, 1],
        "theme": "林轩觉醒金灵根，踏入修仙之路",
        "stage_position": "开篇",
    },
    {
        "name": "拜师篇",
        "chapter_range": [2, 2],
        "theme": "林轩拜入剑峰，跟随赵长老修行",
        "stage_position": "发展",
    },
    {
        "name": "比武篇",
        "chapter_range": [3, 3],
        "theme": "林轩初露锋芒，击败萧云",
        "stage_position": "发展",
    },
    {
        "name": "秘境篇",
        "chapter_range": [4, 4],
        "theme": "天玄秘境历练，获得天玄剑",
        "stage_position": "转折",
    },
    {
        "name": "魔道篇",
        "chapter_range": [5, 5],
        "theme": "魔道来袭，林轩力挽狂澜",
        "stage_position": "高潮",
    },
]

# S3 阶段 LLM 产出的实体（模拟，含 E_module 之外的实体类型）
# info 文本为 ~600-800 字，满足 500-1500 字要求


def _make_info(text: str, target_len: int = 700) -> str:
    """将文本重复填充到目标长度。"""
    if not text:
        return "x" * target_len
    result = text
    while len(result) < target_len:
        result += text
    return result[:target_len]


_MOCK_ENTITIES_DATA = [
    {
        "id": "C_林轩",
        "name": "林轩",
        "type": "character",
        "coords": {"T": "E_module_觉醒篇", "L": "L_青云城", "C": "C_林轩", "E": "", "R": ""},
        "info": _make_info(
            "林轩是青云城铁匠之子，自幼体弱却被同侪嘲笑。"
            "十五岁灵根测试中觉醒罕见的金灵根，拜入青云宗剑峰，"
            "跟随赵长老修行剑道。三年筑基，每日挥剑一万次，"
            "剑意初成。在比武大会中以练气七层击败练气九层的萧云，"
            "声名鹊起。天玄秘境历练中获得天玄剑，修为突飞猛进。"
            "魔道来袭时力抗血煞，保住青云宗，继任剑峰掌教。",
            750,
        ),
    },
    {
        "id": "C_苏瑶",
        "name": "苏瑶",
        "type": "character",
        "coords": {"T": "E_module_秘境篇", "L": "L_天玄秘境", "C": "C_苏瑶", "E": "", "R": ""},
        "info": _make_info(
            "苏瑶是青云宗弟子，精通阵法，性情冷淡。"
            "天玄秘境历练中与林轩结伴，遭遇赤焰狮时布下困阵，"
            "与林轩合力击退凶兽。她对林轩颇为照拂，"
            "在战斗中配合默契，是林轩重要的同门伙伴。",
            600,
        ),
    },
    {
        "id": "C_赵长老",
        "name": "赵长老",
        "type": "character",
        "coords": {"T": "E_module_拜师篇", "L": "L_青云宗", "C": "C_赵长老", "E": "", "R": ""},
        "info": _make_info(
            "赵长老是青云宗三大剑修之一，白发苍苍，目光如炬。"
            "他收林轩为徒，传授剑道筑基功夫。在魔道来袭时"
            "为保护弟子与血煞激战，身负重伤。伤愈后将剑峰掌教"
            "之位传于林轩，是林轩剑道路上的引路人。",
            620,
        ),
    },
    {
        "id": "C_萧云",
        "name": "萧云",
        "type": "character",
        "coords": {"T": "E_module_比武篇", "L": "L_青云宗", "C": "C_萧云", "E": "", "R": ""},
        "info": _make_info(
            "萧云出身世家，修为练气九层，是比武大会热门人选。"
            "他轻视林轩的铁匠出身，却在比试中被林轩三招击败。"
            "此事令他深受打击，也证明了剑道一途重在心境而非修为。",
            550,
        ),
    },
    {
        "id": "C_血煞",
        "name": "血煞",
        "type": "character",
        "coords": {"T": "E_module_魔道篇", "L": "L_青云宗", "C": "C_血煞", "E": "", "R": ""},
        "info": _make_info(
            "血煞是魔道高手，修为高深，手持血色长刀。"
            "他率魔道突袭青云宗，所过之处生灵涂炭。"
            "与赵长老激战将其重伤，又与林轩交手，"
            "最终在宗门援军到来时负伤遁走。",
            580,
        ),
    },
    {
        "id": "L_青云城",
        "name": "青云城",
        "type": "location",
        "coords": {"T": "E_module_觉醒篇", "L": "L_青云城", "C": "", "E": "", "R": ""},
        "info": _make_info(
            "青云城是故事开始的地点，城外有练武场，"
            "每年在此举行灵根测试。林轩在此觉醒金灵根，"
            "踏上修仙之路。城中有铁匠铺，是林轩父亲的谋生之所。",
            520,
        ),
    },
    {
        "id": "L_青云宗",
        "name": "青云宗",
        "type": "location",
        "coords": {"T": "E_module_拜师篇", "L": "L_青云宗", "C": "", "E": "", "R": ""},
        "info": _make_info(
            "青云宗坐落于苍莽山脉之巅，云雾缭绕，殿宇楼阁若隐若现。"
            "宗门有十二峰，剑峰以剑修闻名。赵长老是三大剑修之一。"
            "宗门百年一次开启天玄秘境历练。魔道来袭时，"
            "青云宗弟子死伤惨重，但最终在林轩等人的力战下保住宗门。",
            650,
        ),
    },
    {
        "id": "L_天玄秘境",
        "name": "天玄秘境",
        "type": "location",
        "coords": {"T": "E_module_秘境篇", "L": "L_天玄秘境", "C": "", "E": "", "R": ""},
        "info": _make_info(
            "天玄秘境是上古大能留下的遗迹，百年开启一次。"
            "内藏无数珍宝，也危机四伏。林轩与苏瑶在此遭遇赤焰狮，"
            "合力击退后在巢穴中发现天玄剑。秘境中的经历"
            "让林轩修为突飞猛进。",
            580,
        ),
    },
    {
        "id": "E_觉醒",
        "name": "灵根觉醒",
        "type": "event",
        "coords": {"T": "E_module_觉醒篇", "L": "L_青云城", "C": "C_林轩", "E": "E_觉醒", "R": ""},
        "info": _make_info(
            "灵根觉醒是故事的开端事件。林轩在十五岁灵根测试中，"
            "将手按在测灵石上，测灵石爆发耀眼金色光芒。"
            "测灵长老惊呼为百年难遇的金灵根，乃是剑修的绝佳资质。"
            "此事改变了林轩的命运，使他从一个被嘲笑的废材"
            "成为众人瞩目的天才。",
            600,
        ),
    },
    {
        "id": "E_比武",
        "name": "比武大会",
        "type": "event",
        "coords": {"T": "E_module_比武篇", "L": "L_青云宗", "C": "C_林轩", "E": "E_比武", "R": ""},
        "info": _make_info(
            "比武大会是青云宗内门弟子的年度盛事。林轩作为剑峰代表参赛，"
            "首轮对手是丹峰的萧云。萧云修为练气九层，轻视林轩。"
            "然而林轩以练气七层之境，三招之内击败萧云，"
            "铁剑停在萧云咽喉前寸许。此事在青云宗历史上前所未有，"
            "令林轩声名鹊起。",
            620,
        ),
    },
    {
        "id": "E_魔道来袭",
        "name": "魔道突袭",
        "type": "event",
        "coords": {"T": "E_module_魔道篇", "L": "L_青云宗", "C": "C_林轩", "E": "E_魔道来袭", "R": ""},
        "info": _make_info(
            "魔道突袭是故事的高潮事件。血煞率魔道修士夜袭青云宗，"
            "黑云压城，杀声震天。赵长老为保护弟子与血煞激战身负重伤。"
            "林轩拔出天玄剑，以筑基初期之境力抗魔道高手。"
            "最终宗门援军到来，血煞负伤遁走。经此一役，"
            "林轩名震天下，继任剑峰掌教。",
            680,
        ),
    },
    {
        "id": "I_天玄剑",
        "name": "天玄剑",
        "type": "item",
        "coords": {"T": "E_module_秘境篇", "L": "L_天玄秘境", "C": "", "E": "", "R": ""},
        "info": _make_info(
            "天玄剑是上古大能留下的神兵，剑身铭刻上古符文，"
            "散发幽幽金光。林轩在赤焰狮巢穴中发现此剑，"
            "握住时感到血脉相连的亲切感。此剑与金灵根相合，"
            "成为林轩剑道的重要伙伴，在魔道来袭时发挥关键作用。",
            560,
        ),
    },
]

# S5 阶段 LLM 产出的关系（模拟，description ≤100 字）
_MOCK_RELATIONS_DATA = [
    # T_main 由 timeline_skeleton_builder 构建，这里不重复
    # S_topo 双向：实体→L + L→E_module/E_event
    {"source_id": "C_林轩", "target_id": "L_青云城", "relation_type": "S_topo", "description": "林轩出生于青云城", "strength": "strong"},
    {"source_id": "C_林轩", "target_id": "L_青云宗", "relation_type": "S_topo", "description": "林轩拜入青云宗", "strength": "strong"},
    {"source_id": "C_苏瑶", "target_id": "L_天玄秘境", "relation_type": "S_topo", "description": "苏瑶在秘境历练", "strength": "weak"},
    {"source_id": "C_赵长老", "target_id": "L_青云宗", "relation_type": "S_topo", "description": "赵长老驻锡青云宗", "strength": "strong"},
    {"source_id": "C_血煞", "target_id": "L_青云宗", "relation_type": "S_topo", "description": "血煞袭击青云宗", "strength": "strong"},
    # L→E_module/E_event（S_topo 出边，v0.4.0 微调）
    {"source_id": "L_青云城", "target_id": "E_module_觉醒篇", "relation_type": "S_topo", "description": "觉醒篇发生于青云城", "strength": "weak"},
    {"source_id": "L_青云宗", "target_id": "E_module_拜师篇", "relation_type": "S_topo", "description": "拜师篇发生于青云宗", "strength": "weak"},
    {"source_id": "L_青云宗", "target_id": "E_比武", "relation_type": "S_topo", "description": "比武大会在青云宗举行", "strength": "weak"},
    {"source_id": "L_青云宗", "target_id": "E_魔道来袭", "relation_type": "S_topo", "description": "魔道袭击青云宗", "strength": "weak"},
    {"source_id": "L_天玄秘境", "target_id": "E_module_秘境篇", "relation_type": "S_topo", "description": "秘境篇发生于天玄秘境", "strength": "weak"},
    # A_causal 因果关系
    {"source_id": "E_觉醒", "target_id": "E_比武", "relation_type": "A_causal", "description": "觉醒金灵根使林轩有能力参赛", "strength": "strong"},
    {"source_id": "E_比武", "target_id": "E_魔道来袭", "relation_type": "A_causal", "description": "比武崭露头角后获得历练机会", "strength": "weak"},
    # R_strong 强关联
    {"source_id": "C_林轩", "target_id": "I_天玄剑", "relation_type": "R_strong", "description": "林轩持有天玄剑", "strength": "strong"},
    {"source_id": "C_林轩", "target_id": "C_赵长老", "relation_type": "R_strong", "description": "师徒关系", "strength": "strong"},
    {"source_id": "C_林轩", "target_id": "C_苏瑶", "relation_type": "R_strong", "description": "同门伙伴", "strength": "weak"},
    {"source_id": "C_林轩", "target_id": "C_血煞", "relation_type": "R_strong", "description": "宿敌", "strength": "strong"},
    # A_arc 角色弧光
    {"source_id": "C_林轩", "target_id": "C_林轩", "relation_type": "A_arc", "description": "从废材到掌教的蜕变", "strength": "strong"},
]


def _make_entity(data: dict) -> Entity:
    """从 mock 数据构造 Entity 实例。"""
    return Entity(
        id=data["id"],
        name=data["name"],
        type=data["type"],
        coords=data.get("coords", {}),
        info=data.get("info", ""),
    )


def _make_relation(data: dict) -> Relation:
    """从 mock 数据构造 Relation 实例。"""
    return Relation(
        source_id=data["source_id"],
        target_id=data["target_id"],
        relation_type=data["relation_type"],
        strength=data.get("strength", "weak"),
        description=data.get("description", ""),
    )


# ═══════════════════════════════════════════════════════════
# 端到端管线 Fixture
# ═══════════════════════════════════════════════════════════

@pytest.fixture(scope="module")
def pipeline_result():
    """模拟端到端管线 S1→S2.5→S3→S4→S5→S6→S7 的完整产出。

    Returns:
        dict 含:
          - chunks: S1 文本分块产出
          - titles: S2.5 章节标题抽样
          - e_module_entities: S2.5 E_module 实体
          - t_main_relations: S2.5 T_main 关系
          - entities: S3/S4 全量实体（含 info）
          - relations: S5 全量关系
          - all_entities: E_module + 其他实体
          - all_relations: T_main + 其他关系
    """
    # ─── S1: 文本分块 ───────────────────────────────────────
    chunks = chunk_text(_SAMPLE_NOVEL, chunk_size=2000, overlap=200, source="sample_novel")
    assert len(chunks) > 0, "S1 文本分块应产出非空 chunks"

    # ─── S2.5: 章节标题抽样 + 时序骨架构建 ──────────────────
    titles = sample_chapter_titles(chunks, max_samples=200)
    assert len(titles) > 0, "S2.5 章节标题抽样应产出非空列表"

    e_module_entities, t_main_relations = build_skeleton(_MOCK_PLOT_MODULES)
    assert len(e_module_entities) == 5, "应产出 5 个 E_module 实体"
    assert len(t_main_relations) == 4, "应产出 4 条 T_main 关系"

    # ─── S3/S4: 实体抽取 + info 填充（mock LLM 产出）──────────
    entities = [_make_entity(d) for d in _MOCK_ENTITIES_DATA]

    # ─── S4: info 压缩兜底（对 >1500 字的 info 触发压缩）──────
    # mock 一个压缩回调：截断到 1400 字
    def _mock_compress_fn(prompt: str) -> str:
        """模拟 LLM 压缩：从 prompt 中提取原文并截断到 1400 字。"""
        # prompt 模板中包含原文，简单截断
        return "x" * 1400

    for ent in entities:
        if len(ent.info) > 1500:
            ent.info = compress_info_with_retry(ent.info, _mock_compress_fn)

    # ─── S5: 关系建模（mock LLM 产出）─────────────────────────
    relations = [_make_relation(d) for d in _MOCK_RELATIONS_DATA]

    # ─── S6/S7: 合并全量实体和关系 ───────────────────────────
    all_entities = list(e_module_entities) + entities
    all_relations = list(t_main_relations) + relations

    return {
        "chunks": chunks,
        "titles": titles,
        "e_module_entities": e_module_entities,
        "t_main_relations": t_main_relations,
        "entities": entities,
        "relations": relations,
        "all_entities": all_entities,
        "all_relations": all_relations,
    }


# ═══════════════════════════════════════════════════════════
# 测试 1: CP-E1.1 端到端管线 S1→S2.5→S3→S4→S5→S6→S7 全流程通过
# ═══════════════════════════════════════════════════════════

class TestFullPipeline:
    """端到端管线全流程通过测试。"""

    def test_s1_chunking_produces_chunks(self, pipeline_result):
        """S1: 文本分块产出非空 chunks。"""
        chunks = pipeline_result["chunks"]
        assert len(chunks) > 0
        assert all(isinstance(c, Chunk) for c in chunks)

    def test_s2_5_title_sampling_produces_titles(self, pipeline_result):
        """S2.5: 章节标题抽样产出非空列表。"""
        titles = pipeline_result["titles"]
        assert len(titles) > 0
        assert all("chapter_idx" in t and "title" in t for t in titles)

    def test_s2_5_skeleton_builds_e_modules(self, pipeline_result):
        """S2.5: 时序骨架构建产出 E_module 实体。"""
        e_modules = pipeline_result["e_module_entities"]
        assert len(e_modules) == 5
        assert all(e.type == "E_module" for e in e_modules)

    def test_s2_5_skeleton_builds_t_main(self, pipeline_result):
        """S2.5: 时序骨架构建产出 T_main 关系。"""
        t_main = pipeline_result["t_main_relations"]
        assert len(t_main) == 4
        assert all(r.relation_type == "T_main" for r in t_main)

    def test_s3_entities_extracted(self, pipeline_result):
        """S3: 实体抽取产出全量实体。"""
        entities = pipeline_result["entities"]
        assert len(entities) == len(_MOCK_ENTITIES_DATA)
        # 验证实体类型均合法
        for ent in entities:
            assert ent.type in ENTITY_TYPES, f"非法实体类型: {ent.type}"

    def test_s5_relations_modeled(self, pipeline_result):
        """S5: 关系建模产出全量关系。"""
        relations = pipeline_result["relations"]
        assert len(relations) == len(_MOCK_RELATIONS_DATA)

    def test_full_pipeline_no_errors(self, pipeline_result):
        """端到端管线全流程无报错，产出完整知识图谱。"""
        all_entities = pipeline_result["all_entities"]
        all_relations = pipeline_result["all_relations"]
        # E_module + 其他实体 = 5 + 12 = 17
        assert len(all_entities) == 5 + len(_MOCK_ENTITIES_DATA)
        # T_main + 其他关系 = 4 + 17 = 21
        assert len(all_relations) == 4 + len(_MOCK_RELATIONS_DATA)


# ═══════════════════════════════════════════════════════════
# 测试 2: CP-E1.2 五维坐标唯一值校验通过
# ═══════════════════════════════════════════════════════════

class TestCoordsUnique:
    """五维坐标唯一值校验测试。"""

    def test_all_entities_pass_coords_unique(self, pipeline_result):
        """所有实体 coords 通过 validate_coords_unique 校验。"""
        for ent in pipeline_result["all_entities"]:
            passed = validate_coords_unique(ent.coords)
            assert passed, f"实体 {ent.id} coords 未通过唯一值校验: {ent.coords}"

    def test_all_entities_no_K_dimension(self, pipeline_result):
        """所有实体 coords 不含 K 维度。"""
        for ent in pipeline_result["all_entities"]:
            passed = validate_no_K_dimension(ent.coords)
            assert passed, f"实体 {ent.id} coords 含有 K 维度: {ent.coords}"

    def test_coord_dimensions_are_five(self):
        """COORD_DIMENSIONS 恰好为五维 [T, L, C, E, R]。"""
        assert COORD_DIMENSIONS == ("T", "L", "C", "E", "R")
        assert "K" not in COORD_DIMENSIONS
        assert len(COORD_DIMENSIONS) == 5

    def test_coords_migrator_produces_valid_coords(self):
        """coords_migrator 迁移后的坐标通过五维校验。"""
        old_coords = {
            "T": ["E_module_1", "E_module_2"],
            "L": ["L_青云城"],
            "C": ["C_林轩"],
            "E": ["E_觉醒"],
            "K": ["K_主线"],
            "R": {"R_power": "金灵根"},
        }
        new_coords = migrate_coords(old_coords)
        assert validate_coords_unique(new_coords), "迁移后坐标未通过唯一值校验"
        assert validate_no_K_dimension(new_coords), "迁移后坐标含 K 维度"


# ═══════════════════════════════════════════════════════════
# 测试 3: CP-E1.3 info 字数达标率 >80%
# ═══════════════════════════════════════════════════════════

class TestInfoLength:
    """info 字数达标率测试。"""

    def test_info_pass_rate_above_80_percent(self, pipeline_result):
        """info 字数 ∈ [500, 1500] 的实体占比 >80%。"""
        entities = pipeline_result["entities"]
        total = len(entities)
        passed = 0
        for ent in entities:
            ok, _ = validate_info_length(ent.info)
            if ok:
                passed += 1
        rate = passed / total
        assert rate > 0.8, f"info 达标率 {rate:.1%} 未超过 80% ({passed}/{total})"

    def test_all_info_within_range_after_compression(self, pipeline_result):
        """压缩后所有 info 字数 ∈ [500, 1500]（或触发压缩后达标）。"""
        entities = pipeline_result["entities"]
        for ent in entities:
            ok, status = validate_info_length(ent.info)
            assert ok, f"实体 {ent.id} info 字数不达标: status={status}, len={len(ent.info)}"

    def test_info_compressor_truncates_overlong(self):
        """info_compressor 对 >1500 字 info 触发压缩。"""
        long_info = "x" * 2000
        prompt = compress_info(long_info)
        assert isinstance(prompt, str)
        assert len(prompt) > 0

    def test_info_compressor_rejects_short(self):
        """info_compressor 对 ≤1500 字 info 抛出 ValueError。"""
        short_info = "x" * 500
        with pytest.raises(ValueError):
            compress_info(short_info)


# ═══════════════════════════════════════════════════════════
# 测试 4: CP-E1.4 关系 description 均 ≤100字
# ═══════════════════════════════════════════════════════════

class TestRelationDescLength:
    """关系 description 长度校验测试。"""

    def test_all_relations_desc_within_limit(self, pipeline_result):
        """所有关系 description ≤100 字。"""
        for rel in pipeline_result["all_relations"]:
            ok, status = validate_relation_desc_length(rel.description)
            assert ok, (
                f"关系 {rel.source_id}→{rel.target_id} ({rel.relation_type}) "
                f"description 超长: status={status}, len={len(rel.description)}"
            )

    def test_no_relation_desc_over_100_chars(self, pipeline_result):
        """没有任何关系 description 超过 100 字。"""
        for rel in pipeline_result["all_relations"]:
            assert len(rel.description) <= 100, (
                f"关系 {rel.source_id}→{rel.target_id} description "
                f"长度 {len(rel.description)} > 100"
            )


# ═══════════════════════════════════════════════════════════
# 测试 5: S_topo 双向关系正确
# ═══════════════════════════════════════════════════════════

class TestSTopoBidirectional:
    """S_topo 双向关系测试。"""

    def test_s_topo_bidirectional_validation_passes(self, pipeline_result):
        """S_topo 关系通过 validate_S_topo_bidirectional 校验。"""
        all_relations = pipeline_result["all_relations"]
        passed = validate_S_topo_bidirectional(all_relations)
        assert passed, "S_topo 关系未通过双向校验"

    def test_s_topo_has_inbound_edges(self, pipeline_result):
        """S_topo 存在入边（实体→L）。"""
        s_topo_rels = [r for r in pipeline_result["all_relations"] if r.relation_type == "S_topo"]
        location_targets = {
            r.target_id for r in s_topo_rels
            if any(r.target_id == e.id and e.type == "location" for e in pipeline_result["all_entities"])
        }
        assert len(location_targets) > 0, "S_topo 应有指向 location 的入边"

    def test_s_topo_has_outbound_edges(self, pipeline_result):
        """S_topo 存在出边（L→E_module/E_event）。"""
        s_topo_rels = [r for r in pipeline_result["all_relations"] if r.relation_type == "S_topo"]
        location_ids = {
            e.id for e in pipeline_result["all_entities"] if e.type == "location"
        }
        outbound = [r for r in s_topo_rels if r.source_id in location_ids]
        assert len(outbound) > 0, "S_topo 应有从 location 出发的出边"

    def test_s_topo_bidirectional_nodes_exist(self, pipeline_result):
        """存在同时作为 S_topo source 和 target 的 location 节点（双向）。"""
        s_topo_rels = [r for r in pipeline_result["all_relations"] if r.relation_type == "S_topo"]
        sources = {r.source_id for r in s_topo_rels}
        targets = {r.target_id for r in s_topo_rels}
        bidirectional = sources & targets
        assert len(bidirectional) > 0, (
            "应存在同时作为 S_topo source 和 target 的节点"
        )


# ═══════════════════════════════════════════════════════════
# 测试 6: T_main 仅连接 E_module
# ═══════════════════════════════════════════════════════════

class TestTMainOnlyEModule:
    """T_main 仅连接 E_module 测试。"""

    def test_t_main_validation_passes(self, pipeline_result):
        """T_main 关系通过 validate_E_module_relation 校验。"""
        all_entities = pipeline_result["all_entities"]
        all_relations = pipeline_result["all_relations"]
        passed = validate_E_module_relation(all_entities, all_relations)
        assert passed, "T_main 关系未通过 E_module 约束校验"

    def test_all_t_main_connect_e_module_only(self, pipeline_result):
        """所有 T_main 关系的 source 和 target 均为 E_module 类型。"""
        entity_map = {e.id: e.type for e in pipeline_result["all_entities"]}
        t_main_rels = [
            r for r in pipeline_result["all_relations"] if r.relation_type == "T_main"
        ]
        for rel in t_main_rels:
            src_type = entity_map.get(rel.source_id, "")
            tgt_type = entity_map.get(rel.target_id, "")
            assert src_type == "E_module", (
                f"T_main source {rel.source_id} 类型为 {src_type}，应为 E_module"
            )
            assert tgt_type == "E_module", (
                f"T_main target {rel.target_id} 类型为 {tgt_type}，应为 E_module"
            )

    def test_t_main_rejects_non_e_module(self, pipeline_result):
        """T_main 连接非 E_module 时校验失败。"""
        entities = pipeline_result["all_entities"]
        # 构造一条违规的 T_main 关系（E_module → character）
        bad_relation = Relation(
            source_id="E_module_觉醒篇",
            target_id="C_林轩",
            relation_type="T_main",
        )
        passed = validate_E_module_relation(entities, [bad_relation])
        assert not passed, "T_main 连接非 E_module 应校验失败"


# ═══════════════════════════════════════════════════════════
# 测试 7: E_module 至少有一条 T_main 出边或入边
# ═══════════════════════════════════════════════════════════

class TestEModuleHasTMainEdge:
    """E_module 非孤立节点测试。"""

    def test_all_e_modules_have_t_main_edge(self, pipeline_result):
        """每个 E_module 实体至少有一条 T_main 出边或入边。"""
        e_modules = pipeline_result["e_module_entities"]
        t_main_rels = pipeline_result["t_main_relations"]

        # 收集所有参与 T_main 关系的 E_module ID
        connected_ids = set()
        for rel in t_main_rels:
            connected_ids.add(rel.source_id)
            connected_ids.add(rel.target_id)

        for ent in e_modules:
            assert ent.id in connected_ids, (
                f"E_module {ent.id} 是孤立节点，无 T_main 出边或入边"
            )

    def test_first_e_module_has_outgoing_only(self, pipeline_result):
        """第一个 E_module 有出边（无入边）。"""
        e_modules = pipeline_result["e_module_entities"]
        t_main_rels = pipeline_result["t_main_relations"]
        first = e_modules[0]

        has_outgoing = any(r.source_id == first.id for r in t_main_rels)
        has_incoming = any(r.target_id == first.id for r in t_main_rels)

        assert has_outgoing, "第一个 E_module 应有 T_main 出边"
        assert not has_incoming, "第一个 E_module 不应有 T_main 入边"

    def test_last_e_module_has_incoming_only(self, pipeline_result):
        """最后一个 E_module 有入边（无出边）。"""
        e_modules = pipeline_result["e_module_entities"]
        t_main_rels = pipeline_result["t_main_relations"]
        last = e_modules[-1]

        has_outgoing = any(r.source_id == last.id for r in t_main_rels)
        has_incoming = any(r.target_id == last.id for r in t_main_rels)

        assert has_incoming, "最后一个 E_module 应有 T_main 入边"
        assert not has_outgoing, "最后一个 E_module 不应有 T_main 出边"

    def test_middle_e_modules_have_both(self, pipeline_result):
        """中间的 E_module 既有入边也有出边。"""
        e_modules = pipeline_result["e_module_entities"]
        t_main_rels = pipeline_result["t_main_relations"]

        for ent in e_modules[1:-1]:
            has_outgoing = any(r.source_id == ent.id for r in t_main_rels)
            has_incoming = any(r.target_id == ent.id for r in t_main_rels)
            assert has_outgoing, f"中间 E_module {ent.id} 应有 T_main 出边"
            assert has_incoming, f"中间 E_module {ent.id} 应有 T_main 入边"


# ═══════════════════════════════════════════════════════════
# 测试 8: info_cohesion 节点详情内聚校验
# ═══════════════════════════════════════════════════════════

class TestInfoCohesion:
    """节点详情内聚校验测试（S5 信息架构原则）。"""

    def test_entities_pass_info_cohesion(self, pipeline_result):
        """实体通过 validate_info_cohesion 校验（无拒绝级问题）。"""
        entities = pipeline_result["entities"]
        relations = pipeline_result["all_relations"]

        for ent in entities:
            # 收集该实体的出边
            out_rels = [r for r in relations if r.source_id == ent.id]
            ok, status = validate_info_cohesion(ent, out_rels)
            assert ok, (
                f"实体 {ent.id} 未通过 info_cohesion 校验: "
                f"status={status}, info_len={len(ent.info)}, out_edges={len(out_rels)}"
            )


# ═══════════════════════════════════════════════════════════
# 测试 9: 端到端交叉校验（跨轨道协同）
# ═══════════════════════════════════════════════════════════

class TestCrossTrackValidation:
    """跨轨道协同校验测试。"""

    def test_track_a_b_c_d_integration(self, pipeline_result):
        """Track A (校验函数) + Track B (工具链) + Track C (迁移/压缩) 协同工作。"""
        all_entities = pipeline_result["all_entities"]
        all_relations = pipeline_result["all_relations"]

        # Track A: 校验函数全部可用
        assert validate_coords_unique({"T": "x", "L": "y", "C": "z", "E": "w", "R": "v"})
        assert validate_no_K_dimension({"T": "x"})
        ok, _ = validate_info_length("x" * 600)
        assert ok

        # Track B: 工具链产出正确
        assert len(pipeline_result["e_module_entities"]) == 5
        assert len(pipeline_result["t_main_relations"]) == 4

        # Track C: 迁移工具可用
        migrated = migrate_coords({
            "T": ["old_T"], "L": ["old_L"], "C": ["old_C"],
            "E": ["old_E"], "K": ["old_K"], "R": {"R_power": "old_R"},
        })
        assert validate_coords_unique(migrated)
        assert validate_no_K_dimension(migrated)

        # Track C: 压缩工具可用
        prompt = compress_info("x" * 2000)
        assert isinstance(prompt, str)

    def test_e_module_relation_validation_with_full_graph(self, pipeline_result):
        """全图 E_module 关系校验通过（T-B2 × T-A2 交叉校验）。"""
        all_entities = pipeline_result["all_entities"]
        all_relations = pipeline_result["all_relations"]
        passed = validate_E_module_relation(all_entities, all_relations)
        assert passed

    def test_s_topo_validation_with_full_graph(self, pipeline_result):
        """全图 S_topo 双向校验通过（T-D1 × T-A2 交叉校验）。"""
        all_relations = pipeline_result["all_relations"]
        passed = validate_S_topo_bidirectional(all_relations)
        assert passed
