from __future__ import annotations

import pytest

def test_app_main_importable():
    import app.main
    assert app.main is not None


def test_layout_agent_importable():
    from model.layout_agent import LayoutAgent
    assert LayoutAgent is not None


def test_refine_agent_importable():
    from model.refine_agent import RefineAgent
    assert RefineAgent is not None


def test_validate_agent_importable():
    from model.validate_agent import ValidateAgent
    assert ValidateAgent is not None


def test_llm_client_importable():
    from model.llm_client import default_client, default_model, call_llm
    assert default_client is not None
    assert default_model == "test-model"
    assert call_llm is not None


def test_get_intent_importable():
    from model.layout_tools.get_intent import generate_intent, LayoutFile, LayoutGroup, validate_layout_file
    from model.layout_tools.get_intent import IntentModelOutputError, IntentModelTimeoutError, IntentModelUnavailableError, StructuredPromptError
    assert generate_intent is not None
    assert LayoutFile is not None
    assert LayoutGroup is not None
    assert validate_layout_file is not None
    assert IntentModelOutputError is not None
    assert IntentModelTimeoutError is not None
    assert IntentModelUnavailableError is not None
    assert StructuredPromptError is not None


def test_generate_gird_not_importable():
    import importlib
    import sys
    if "model.generate_gird" in sys.modules:
        del sys.modules["model.generate_gird"]
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("model.generate_gird")


def test_old_search_service_not_importable():
    import importlib
    import sys
    for name in ("model.search_service",):
        if name in sys.modules:
            del sys.modules[name]
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("model.search_service")


def test_old_compute_position_not_importable():
    import importlib
    import sys
    for name in ("model.compute_position",):
        if name in sys.modules:
            del sys.modules[name]
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("model.compute_position")


def test_old_get_background_not_importable():
    import importlib
    import sys
    for name in ("model.get_background",):
        if name in sys.modules:
            del sys.modules[name]
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("model.get_background")


def test_old_get_connection_not_importable():
    import importlib
    import sys
    for name in ("model.get_connection",):
        if name in sys.modules:
            del sys.modules[name]
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("model.get_connection")


def test_old_get_intent_not_importable():
    import importlib
    import sys
    for name in ("model.get_intent",):
        if name in sys.modules:
            del sys.modules[name]
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("model.get_intent")


def test_old_layout_intent_rules_not_importable():
    import importlib
    import sys
    for name in ("model.layout_intent_rules",):
        if name in sys.modules:
            del sys.modules[name]
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("model.layout_intent_rules")


def test_new_control_tools_search_service_importable():
    from model.control_tools.search_service import search_controls_with_threshold, set_control_chunk, SIMILARITY_THRESHOLD
    assert search_controls_with_threshold is not None
    assert set_control_chunk is not None
    assert SIMILARITY_THRESHOLD == 0.55


def test_new_layout_tools_importable():
    from model.layout_tools.compute_position import convert_layout_file, compute_nodes, MissingMaterialError
    from model.layout_tools.get_background import generate_layout, rescale_canvas
    from model.layout_tools.get_connection import generate_connections, ConnectionSpec, ConnectionEnd
    from model.layout_tools.layout_intent_rules import build_rule_layout, RuleLayoutResult
    assert convert_layout_file is not None
    assert compute_nodes is not None
    assert MissingMaterialError is not None
    assert generate_layout is not None
    assert rescale_canvas is not None
    assert generate_connections is not None
    assert ConnectionSpec is not None
    assert ConnectionEnd is not None
    assert build_rule_layout is not None
    assert RuleLayoutResult is not None
