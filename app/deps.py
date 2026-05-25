import threading
from typing import Optional
from data.material_db import MaterialDB
from model.canva_agent import CanvasAgent
from model.control_agent import ControlAgent


_lock = threading.Lock()
_control_agent: Optional[ControlAgent] = None
_canvas_agent: Optional[CanvasAgent] = None
_material_db: Optional[MaterialDB] = None


def get_control_agent() -> ControlAgent:
    global _control_agent
    if _control_agent is None:
        with _lock:
            if _control_agent is None:
                _control_agent = ControlAgent(db=get_material_db())
    return _control_agent


def get_canvas_agent() -> CanvasAgent:
    global _canvas_agent
    if _canvas_agent is None:
        with _lock:
            if _canvas_agent is None:
                _canvas_agent = CanvasAgent()
    return _canvas_agent


def get_material_db() -> MaterialDB:
    global _material_db
    if _material_db is None:
        with _lock:
            if _material_db is None:
                db = MaterialDB()
                db.init_db()
                _material_db = db
    return _material_db