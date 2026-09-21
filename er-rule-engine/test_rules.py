# -*- coding: utf-8 -*-
"""
规则引擎测试
=============
直接运行：python test_rules.py
不需要 pytest，自带断言和输出。
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from engine import run_all_rules
from rules import ALL_RULES

passed = 0
failed = 0


def check(name, er_data, expect_error_rules=None, expect_error_count=None):
    """运行规则并对比期望结果"""
    global passed, failed
    result = run_all_rules(er_data)
    errors = result["errors"]
    actual_rules = {e["rule_id"] for e in errors if e["level"] == "error"}

    ok = True
    if expect_error_rules is not None:
        if actual_rules != expect_error_rules:
            ok = False
    if expect_error_count is not None:
        if result["summary"]["errors"] != expect_error_count:
            ok = False

    if ok:
        print(f"  ✅ {name}")
        passed += 1
    else:
        print(f"  ❌ {name}")
        if expect_error_rules is not None:
            print(f"     期望 error 规则: {expect_error_rules}")
            print(f"     实际 error 规则: {actual_rules}")
        if expect_error_count is not None:
            print(f"     期望 error 数量: {expect_error_count}, 实际: {result['summary']['errors']}")
        for e in errors:
            icon = "🔴" if e["level"] == "error" else "🟠"
            print(f"     {icon} [{e['rule_id']}] {e['message']}")
        failed += 1


# ======================================================================
# 测试用例
# ======================================================================

def make_entity(eid, name, attrs=None, is_weak=False):
    return {
        "id": eid,
        "name": name,
        "is_weak": is_weak,
        "attributes": attrs or [],
    }


def make_attr(name, is_pk=False, is_nullable=True, **kw):
    d = {"name": name, "is_primary_key": is_pk, "is_nullable": is_nullable}
    d.update(kw)
    return d


def make_rel(rid, name, frm, to, card="M:N", attrs=None):
    return {
        "id": rid, "name": name,
        "from_entity": frm, "to_entity": to,
        "cardinality": card,
        "attributes": attrs or [],
    }


def test_perfect():
    """完美 ER 图 —— 0 个 error"""
    er = {
        "entities": [
            make_entity("e1", "学生", [
                make_attr("学号", is_pk=True, is_nullable=False),
                make_attr("姓名"),
            ]),
            make_entity("e2", "课程", [
                make_attr("课程号", is_pk=True, is_nullable=False),
                make_attr("课程名"),
            ]),
        ],
        "relationships": [
            make_rel("r1", "选课", "e1", "e2", "M:N",
                     [make_attr("成绩")]),
        ],
    }
    check("完美 ER 图（0 error）", er, expect_error_rules=set())


def test_no_pk():
    """实体缺主键 → R03"""
    er = {
        "entities": [
            make_entity("e1", "学生", [make_attr("姓名")]),
            make_entity("e2", "课程", [
                make_attr("课程号", is_pk=True, is_nullable=False),
                make_attr("课程名"),
            ]),
        ],
        "relationships": [
            make_rel("r1", "选课", "e1", "e2", "M:N", [make_attr("成绩")]),
        ],
    }
    check("实体缺主键 → R03", er, expect_error_rules={"R03"})


def test_empty_entity_name():
    """实体无名 → R01"""
    er = {
        "entities": [
            make_entity("e1", "", [
                make_attr("学号", is_pk=True, is_nullable=False),
            ]),
            make_entity("e2", "课程", [
                make_attr("课程号", is_pk=True, is_nullable=False),
            ]),
        ],
        "relationships": [
            make_rel("r1", "选课", "e1", "e2", "M:N", [make_attr("成绩")]),
        ],
    }
    check("实体无名 → R01", er, expect_error_rules={"R01"})


def test_dup_entity_name():
    """实体重名 → R02"""
    er = {
        "entities": [
            make_entity("e1", "学生", [
                make_attr("学号", is_pk=True, is_nullable=False),
            ]),
            make_entity("e2", "学生", [
                make_attr("学号", is_pk=True, is_nullable=False),
            ]),
        ],
        "relationships": [
            make_rel("r1", "选课", "e1", "e2", "M:N"),
        ],
    }
    check("实体重名 → R02", er, expect_error_rules={"R02"})


def test_no_attrs():
    """实体无属性 → R04"""
    er = {
        "entities": [
            make_entity("e1", "学生"),  # 无属性
            make_entity("e2", "课程", [
                make_attr("课程号", is_pk=True, is_nullable=False),
            ]),
        ],
        "relationships": [
            make_rel("r1", "选课", "e1", "e2", "M:N"),
        ],
    }
    check("实体无属性 → R03+R04", er, expect_error_rules={"R03", "R04"})


def test_no_cardinality():
    """联系缺基数 → R17"""
    er = {
        "entities": [
            make_entity("e1", "学生", [
                make_attr("学号", is_pk=True, is_nullable=False),
            ]),
            make_entity("e2", "课程", [
                make_attr("课程号", is_pk=True, is_nullable=False),
            ]),
        ],
        "relationships": [
            make_rel("r1", "选课", "e1", "e2", card=""),
        ],
    }
    check("联系缺基数 → R17", er, expect_error_rules={"R17"})


def test_invalid_cardinality():
    """非法基数 → R18"""
    er = {
        "entities": [
            make_entity("e1", "学生", [
                make_attr("学号", is_pk=True, is_nullable=False),
            ]),
            make_entity("e2", "课程", [
                make_attr("课程号", is_pk=True, is_nullable=False),
            ]),
        ],
        "relationships": [
            make_rel("r1", "选课", "e1", "e2", card="N:M"),  # 应为 M:N
        ],
    }
    check("非法基数 → R18", er, expect_error_rules={"R18"})


def test_dangling_relationship():
    """联系指向不存在的实体 → R19"""
    er = {
        "entities": [
            make_entity("e1", "学生", [
                make_attr("学号", is_pk=True, is_nullable=False),
            ]),
        ],
        "relationships": [
            make_rel("r1", "选课", "e1", "e999", "M:N"),  # e999 不存在
        ],
    }
    # e1 有主键（学号 is_pk=True），所以 R03 不会触发
    check("联系悬空 → R19", er, expect_error_rules={"R19"})


def test_orphan_entity():
    """孤立实体 → R08 (warning)"""
    er = {
        "entities": [
            make_entity("e1", "学生", [
                make_attr("学号", is_pk=True, is_nullable=False),
            ]),
            make_entity("e2", "课程", [
                make_attr("课程号", is_pk=True, is_nullable=False),
            ]),
            make_entity("e3", "学院", [  # 孤立，没有联系
                make_attr("学院号", is_pk=True, is_nullable=False),
            ]),
        ],
        "relationships": [
            make_rel("r1", "选课", "e1", "e2", "M:N", [make_attr("成绩")]),
        ],
    }
    check("孤立实体 → 0 error（R08 是 warning）", er, expect_error_rules=set())


def test_weak_entity_no_partial_key():
    """弱实体缺鉴别器 → R05"""
    er = {
        "entities": [
            make_entity("e1", "学生", [
                make_attr("学号", is_pk=True, is_nullable=False),
            ]),
            make_entity("e2", "选课记录", [  # 弱实体但没有 partial_key
                make_attr("选课时间"),
            ], is_weak=True),
        ],
        "relationships": [
            make_rel("r1", "拥有", "e1", "e2", "1:N"),
        ],
    }
    check("弱实体缺鉴别器 → R05", er, expect_error_rules={"R05"})


def test_pk_multivalued():
    """主键是多值属性 → R06"""
    er = {
        "entities": [
            make_entity("e1", "学生", [
                make_attr("学号", is_pk=True, is_nullable=False, is_multi_valued=True),
            ]),
            make_entity("e2", "课程", [
                make_attr("课程号", is_pk=True, is_nullable=False),
            ]),
        ],
        "relationships": [
            make_rel("r1", "选课", "e1", "e2", "M:N"),
        ],
    }
    check("主键多值 → R06", er, expect_error_rules={"R06"})


def test_pk_nullable():
    """主键可为空 → R11"""
    er = {
        "entities": [
            make_entity("e1", "学生", [
                make_attr("学号", is_pk=True, is_nullable=True),  # 主键不应可空
            ]),
            make_entity("e2", "课程", [
                make_attr("课程号", is_pk=True, is_nullable=False),
            ]),
        ],
        "relationships": [
            make_rel("r1", "选课", "e1", "e2", "M:N"),
        ],
    }
    check("主键可空 → R11", er, expect_error_rules={"R11"})


def test_empty_er():
    """空 ER 图 → R24"""
    er = {"entities": [], "relationships": []}
    check("空 ER 图 → R24", er, expect_error_rules={"R24"})


def test_multi_entities_no_relations():
    """多实体无联系 → R25 (warning)"""
    er = {
        "entities": [
            make_entity("e1", "学生", [
                make_attr("学号", is_pk=True, is_nullable=False),
            ]),
            make_entity("e2", "课程", [
                make_attr("课程号", is_pk=True, is_nullable=False),
            ]),
        ],
        "relationships": [],
    }
    check("多实体无联系 → 0 error（R25 是 warning）", er, expect_error_rules=set())


def test_dup_attr_name():
    """同实体内属性重名 → R10"""
    er = {
        "entities": [
            make_entity("e1", "学生", [
                make_attr("学号", is_pk=True, is_nullable=False),
                make_attr("姓名"),
                make_attr("姓名"),  # 重复
            ]),
            make_entity("e2", "课程", [
                make_attr("课程号", is_pk=True, is_nullable=False),
            ]),
        ],
        "relationships": [
            make_rel("r1", "选课", "e1", "e2", "M:N"),
        ],
    }
    check("属性重名 → R10", er, expect_error_rules={"R10"})


def test_weak_no_strong():
    """弱实体未依赖强实体 → R28"""
    er = {
        "entities": [
            make_entity("e1", "学生", [
                make_attr("学号", is_pk=True, is_nullable=False),
            ]),
            make_entity("e2", "弱记录", [
                make_attr("序号", is_partial_key=True),
            ], is_weak=True),
        ],
        "relationships": [],  # 弱实体没有联系到强实体
    }
    # 弱实体有 partial_key（序号），所以 R05 不触发；无联系到强实体 → R28
    check("弱实体无强实体依赖 → R28", er, expect_error_rules={"R28"})


def test_requirement_alignment():
    """需求对齐：需求提到教师但图中没有 → R29"""
    er = {
        "entities": [
            make_entity("e1", "学生", [
                make_attr("学号", is_pk=True, is_nullable=False),
                make_attr("姓名"),
            ]),
            make_entity("e2", "课程", [
                make_attr("课程号", is_pk=True, is_nullable=False),
                make_attr("课程名"),
            ]),
        ],
        "relationships": [
            make_rel("r1", "选课", "e1", "e2", "M:N", [make_attr("成绩")]),
        ],
        "requirement_text": "学生可以选课，教师可以授课，系统需要记录学生成绩和教师信息",
    }
    check("需求对齐（缺教师）→ 0 error（R29 是 warning）", er, expect_error_rules=set())


def test_requirement_alignment_full():
    """需求对齐：全部覆盖 → 0 warning"""
    er = {
        "entities": [
            make_entity("e1", "学生", [
                make_attr("学号", is_pk=True, is_nullable=False),
                make_attr("姓名"),
            ]),
            make_entity("e2", "课程", [
                make_attr("课程号", is_pk=True, is_nullable=False),
                make_attr("课程名"),
            ]),
            make_entity("e3", "教师", [
                make_attr("工号", is_pk=True, is_nullable=False),
            ]),
        ],
        "relationships": [
            make_rel("r1", "选课", "e1", "e2", "M:N", [make_attr("成绩")]),
            make_rel("r2", "授课", "e3", "e2", "1:N"),
        ],
        "requirement_text": "学生可以选课，教师可以授课",
    }
    check("需求全覆盖 → 0 error", er, expect_error_rules=set())


# ======================================================================
# 运行所有测试
# ======================================================================

if __name__ == "__main__":
    print(f"\n{'='*60}")
    print(f"  ER 规则引擎测试（{len(ALL_RULES)} 条规则）")
    print(f"{'='*60}\n")

    test_perfect()
    test_no_pk()
    test_empty_entity_name()
    test_dup_entity_name()
    test_no_attrs()
    test_no_cardinality()
    test_invalid_cardinality()
    test_dangling_relationship()
    test_orphan_entity()
    test_weak_entity_no_partial_key()
    test_pk_multivalued()
    test_pk_nullable()
    test_empty_er()
    test_multi_entities_no_relations()
    test_dup_attr_name()
    test_weak_no_strong()
    test_requirement_alignment()
    test_requirement_alignment_full()

    print(f"\n{'='*60}")
    print(f"  结果：{passed} 通过，{failed} 失败")
    print(f"{'='*60}\n")

    if failed > 0:
        sys.exit(1)
