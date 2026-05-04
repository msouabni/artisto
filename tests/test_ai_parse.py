"""Tests unitaires pour le parsing des réponses Ollama dans ai.py."""
import sys
sys.path.insert(0, "src")

from api.routes.ai import _parse_json_response, _repair_json_llm_typos, _strip_think_tags


def test_strip_think_tags():
    raw = "<think>Je vais générer des enfants...</think>{\"children\": []}"
    result = _strip_think_tags(raw)
    assert "<think>" not in result
    assert "{" in result


def test_strip_think_tags_multiline():
    raw = "<think>\nLong reasoning\nmore text\n</think>\n[{\"id\": \"a\"}]"
    result = _strip_think_tags(raw)
    assert "<think>" not in result
    assert "[" in result


def test_parse_direct_array():
    raw = '[{"id": "chat", "name_fr": "Chat", "name_en": "Cat", "slug": "cat"}]'
    result = _parse_json_response(raw)
    assert isinstance(result, list)
    assert result[0]["id"] == "chat"


def test_parse_direct_object():
    raw = '{"children": [{"id": "chien", "name_fr": "Chien"}]}'
    result = _parse_json_response(raw)
    assert isinstance(result, dict)
    assert "children" in result


def test_parse_with_think_tags():
    raw = '<think>Generating...</think>{"children": [{"id": "oiseau", "name_fr": "Oiseau"}]}'
    result = _parse_json_response(raw)
    assert isinstance(result, dict)
    assert "children" in result


def test_parse_array_with_think_tags():
    raw = '<think>Let me think</think>[{"id": "lion", "name_fr": "Lion", "name_en": "Lion"}]'
    result = _parse_json_response(raw)
    assert isinstance(result, list)
    assert result[0]["id"] == "lion"


def test_parse_wrapped_unknown_key():
    raw = '{"suggested_terms": [{"id": "tigre", "name_fr": "Tigre"}]}'
    result = _parse_json_response(raw)
    assert isinstance(result, dict)
    assert "suggested_terms" in result


def test_parse_markdown_code_block():
    raw = '```json\n[{"id": "renard", "name_fr": "Renard"}]\n```'
    result = _parse_json_response(raw)
    assert isinstance(result, list)
    assert result[0]["id"] == "renard"


def test_repair_double_quote_before_key():
    broken = '[{"id": "a", "w": 0}, {"id": "b", ""weight": 1}]'
    fixed = _repair_json_llm_typos(broken)
    assert '""weight"' not in fixed
    result = _parse_json_response(broken)
    assert isinstance(result, list)
    assert len(result) == 2
    assert result[1]["id"] == "b"


def test_parse_malformed_array_like_browser_response():
    """Régression : typo LLM ""weight"" casse le tableau JSON (cas réel navigateur)."""
    raw = """[
  {"id": "mickey", "slug": "m", "name_en": "M", "name_fr": "M",
    "description_en": "d", "description_fr": "Coloriage de Minnie, parfait pour le printemps.", ""weight": 5}
]"""
    result = _parse_json_response(raw)
    assert isinstance(result, list)
    assert len(result) == 1
    assert result[0].get("id") == "mickey"
    assert result[0].get("weight") == 5


if __name__ == "__main__":
    tests = [
        test_strip_think_tags,
        test_strip_think_tags_multiline,
        test_parse_direct_array,
        test_parse_direct_object,
        test_parse_with_think_tags,
        test_parse_array_with_think_tags,
        test_parse_wrapped_unknown_key,
        test_parse_markdown_code_block,
        test_repair_double_quote_before_key,
        test_parse_malformed_array_like_browser_response,
    ]
    passed = 0
    for t in tests:
        try:
            t()
            print(f"  PASS  {t.__name__}")
            passed += 1
        except Exception as e:
            print(f"  FAIL  {t.__name__}: {e}")
    print(f"\n{passed}/{len(tests)} tests passed")
