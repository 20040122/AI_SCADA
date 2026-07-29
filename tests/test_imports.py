from __future__ import annotations


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
