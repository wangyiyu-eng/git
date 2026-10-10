"""
knowledge/kg_builder.py
基于 networkx 构建学科知识点有向图：节点=知识点，边=知识点关系。
轻量化：JSON 数据 + 内存图，毕设无需 Neo4j。
"""
import importlib.util
import os
from typing import Dict, List, Tuple

import networkx as nx

from utils.io_helper import load_json


def _load_config():
    cfg_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.py")
    spec = importlib.util.spec_from_file_location("app_config", cfg_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_CONFIG = _load_config()


class KnowledgeGraph:
    """封装 networkx DiGraph，提供教学评估所需查询接口。"""

    def __init__(self, data_path: str = None):
        self.data_path = data_path or _CONFIG.KG_DATA_FILE
        self.data = load_json(self.data_path)
        self.G = nx.DiGraph()
        self._build()

    def _build(self):
        # 节点
        for n in self.data.get("nodes", []):
            self.G.add_node(
                n["id"],
                name=n["name"],
                difficulty=n.get("difficulty", 1),
                subject=n.get("subject", "general"),
            )
        # 边
        for e in self.data.get("edges", []):
            self.G.add_edge(e["src"], e["dst"], type=e.get("type", "related"))

    # ========== 查询接口 ==========
    def get_name(self, node_id: str) -> str:
        if node_id in self.G.nodes:
            return self.G.nodes[node_id].get("name", node_id)
        return node_id

    def get_node_ids(self) -> List[str]:
        return list(self.G.nodes)

    def prerequisites(self, node_id: str) -> List[str]:
        """直接先修（前驱节点）。"""
        if node_id not in self.G:
            return []
        return list(self.G.predecessors(node_id))

    def all_prerequisites(self, node_id: str) -> List[str]:
        """所有先修（递归前驱）。"""
        if node_id not in self.G:
            return []
        visited = set()
        stack = list(self.G.predecessors(node_id))
        while stack:
            cur = stack.pop()
            if cur in visited:
                continue
            visited.add(cur)
            stack.extend(self.G.predecessors(cur))
        return list(visited)

    def related_synonyms(self, node_id: str) -> List[str]:
        return self.data.get("synonyms", {}).get(node_id, [])

    def default_chain(self) -> List[str]:
        return self.data.get("default_chain", [])

    def to_dict_for_frontend(self) -> Dict:
        """导出为前端可视化友好的字典（含 nodes / edges）。"""
        nodes = [
            {"id": nid, "name": self.G.nodes[nid]["name"],
             "difficulty": self.G.nodes[nid]["difficulty"]}
            for nid in self.G.nodes
        ]
        edges = [
            {"source": u, "target": v, "type": d.get("type", "related")}
            for u, v, d in self.G.edges(data=True)
        ]
        return {"nodes": nodes, "edges": edges, "subject": self.data.get("subject", "")}

    def match_knowledge_point(self, text: str) -> Tuple[str, float]:
        """
        通过同义词表把模型输出/学生作答中的文本匹配到知识点节点。
        返回 (node_id, score)，未匹配返回 ("", 0.0)。
        """
        if not text:
            return "", 0.0
        text_low = str(text).lower()
        best = ("", 0.0)
        for node_id, syns in self.data.get("synonyms", {}).items():
            for s in syns:
                if s and s in text:
                    return node_id, 1.0
                if s and s.lower() in text_low:
                    return node_id, 0.8
        # 命中节点名
        for node_id, attrs in self.G.nodes(data=True):
            name = attrs.get("name", "")
            if name and name in text:
                return node_id, 0.9
        return best

    def match_knowledge_batch(self, texts: List[str]) -> List[str]:
        """批量匹配，返回命中的节点 ID 列表（去重）。"""
        seen = []
        for t in texts or []:
            nid, score = self.match_knowledge_point(t)
            if nid and nid not in seen:
                seen.append(nid)
        return seen


# 单例加载器（避免每次重复建图）
_KG_INSTANCE = None


def get_kg() -> KnowledgeGraph:
    global _KG_INSTANCE
    if _KG_INSTANCE is None:
        _KG_INSTANCE = KnowledgeGraph()
    return _KG_INSTANCE