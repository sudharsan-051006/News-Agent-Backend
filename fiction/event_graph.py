"""
Event Graph & Multi-Hop Traversal Module for Elinity Fiction Engine.
Provides graph-theoretic analysis of events and entities in PostgreSQL:
- Multi-hop pathfinding (2-3 hops) across events and entities.
- Subgraph density and centrality scoring.
- Narrative cluster candidate discovery (3 to 6 connected events).
"""

import logging
from collections import defaultdict, deque
from typing import List, Dict, Any, Set, Tuple, Optional

logger = logging.getLogger("fiction.event_graph")


class EventGraph:
    """
    In-memory graph representation of events, entities, and relationships
    for fast traversal and cluster candidate generation.
    """

    def __init__(self):
        # Adjacency list: node_id -> set of (neighbor_id, relation_type, weight)
        self.adj: Dict[str, List[Tuple[str, str, float]]] = defaultdict(list)
        self.node_types: Dict[str, str] = {}  # "event" or "entity"
        self.node_metadata: Dict[str, Dict[str, Any]] = {}

    def add_event(self, event_id: int, metadata: Dict[str, Any] = None):
        key = f"event:{event_id}"
        self.node_types[key] = "event"
        self.node_metadata[key] = metadata or {}
        if key not in self.adj:
            self.adj[key] = []

    def add_entity(self, entity_id: int, canonical_name: str, metadata: Dict[str, Any] = None):
        key = f"entity:{entity_id}"
        self.node_types[key] = "entity"
        meta = metadata or {}
        meta["canonical_name"] = canonical_name
        self.node_metadata[key] = meta
        if key not in self.adj:
            self.adj[key] = []

    def add_event_entity_edge(self, event_id: int, entity_id: int, role: str = "PARTICIPANT"):
        ev_key = f"event:{event_id}"
        ent_key = f"entity:{entity_id}"
        self.adj[ev_key].append((ent_key, f"HAS_ENTITY_{role}", 1.0))
        self.adj[ent_key].append((ev_key, f"PART_OF_{role}", 1.0))

    def add_event_relation_edge(
        self,
        event_a_id: int,
        event_b_id: int,
        relation_type: str,
        is_verified: bool = False,
        weight: float = 1.0
    ):
        ea_key = f"event:{event_a_id}"
        eb_key = f"event:{event_b_id}"
        self.adj[ea_key].append((eb_key, relation_type, weight))
        self.adj[eb_key].append((ea_key, relation_type, weight))

    def find_shortest_path(self, start_event_id: int, end_event_id: int) -> Optional[List[str]]:
        """Finds shortest path between two events using BFS."""
        start_key = f"event:{start_event_id}"
        end_key = f"event:{end_event_id}"

        if start_key not in self.adj or end_key not in self.adj:
            return None

        queue = deque([[start_key]])
        visited = {start_key}

        while queue:
            path = queue.popleft()
            node = path[-1]

            if node == end_key:
                return path

            for neighbor, _, _ in self.adj.get(node, []):
                if neighbor not in visited:
                    visited.add(neighbor)
                    new_path = list(path)
                    new_path.append(neighbor)
                    queue.append(new_path)

        return None

    def get_multi_hop_connected_events(
        self,
        start_event_id: int,
        max_hops: int = 3
    ) -> List[Tuple[int, int, List[str]]]:
        """
        Finds all events within max_hops of start_event_id.
        Returns list of (target_event_id, hop_count, path).
        """
        start_key = f"event:{start_event_id}"
        if start_key not in self.adj:
            return []

        results = []
        queue = deque([(start_key, [start_key], 0)])
        visited = {start_key}

        while queue:
            current, path, hops = queue.popleft()
            if hops >= max_hops:
                continue

            for neighbor, rel, _ in self.adj.get(current, []):
                if neighbor not in visited:
                    visited.add(neighbor)
                    new_path = path + [neighbor]
                    new_hops = hops + 1
                    if neighbor.startswith("event:"):
                        ev_id = int(neighbor.split(":")[1])
                        results.append((ev_id, new_hops, new_path))
                    queue.append((neighbor, new_path, new_hops))

        return results

    def extract_candidate_clusters(
        self,
        min_events: int = 3,
        max_events: int = 6
    ) -> List[List[int]]:
        """
        Finds connected clusters of events (3 to 6 events per cluster).
        Uses community/connected component search over the event projection.
        """
        event_nodes = [k for k in self.adj.keys() if k.startswith("event:")]
        if len(event_nodes) < min_events:
            return []

        # Build event-to-event projection with direct and 2-hop (via entity) weights
        event_ids = [int(k.split(":")[1]) for k in event_nodes]
        event_neighbors: Dict[int, Set[int]] = defaultdict(set)

        for ev_id in event_ids:
            multi_hop = self.get_multi_hop_connected_events(ev_id, max_hops=2)
            for target_id, hops, _ in multi_hop:
                if target_id != ev_id:
                    event_neighbors[ev_id].add(target_id)
                    event_neighbors[target_id].add(ev_id)

        # Greedy narrative cluster formation
        clusters: List[List[int]] = []
        assigned: Set[int] = set()

        # Sort events by connectivity (degree centrality)
        sorted_events = sorted(
            event_ids,
            key=lambda e: len(event_neighbors.get(e, set())),
            reverse=True
        )

        for seed in sorted_events:
            if seed in assigned:
                continue

            # Grow cluster around seed
            cluster = [seed]
            neighbors = sorted(
                list(event_neighbors.get(seed, set())),
                key=lambda e: len(event_neighbors.get(e, set()) & set(cluster)),
                reverse=True
            )

            for n in neighbors:
                if n not in cluster and len(cluster) < max_events:
                    cluster.append(n)

            if len(cluster) >= min_events:
                clusters.append(cluster)
                assigned.update(cluster)

        # If any leftovers can form at least min_events
        unassigned = [e for e in event_ids if e not in assigned]
        if len(unassigned) >= min_events:
            clusters.append(unassigned[:max_events])

        return clusters


def build_graph_from_db(events: List[Dict[str, Any]], relations: List[Dict[str, Any]]) -> EventGraph:
    """Constructs an EventGraph instance from database records."""
    graph = EventGraph()

    # 1. Add all events and their linked entities
    for ev in events:
        ev_id = ev["id"]
        graph.add_event(ev_id, {
            "title": ev.get("title", ""),
            "topics": ev.get("topics", []),
            "event_date": str(ev.get("event_date", "")),
            "country": ev.get("country", "")
        })

        for ent in ev.get("entities", []):
            ent_id = ent.get("entity_id")
            canonical_name = ent.get("canonical_name")
            if ent_id and canonical_name:
                graph.add_entity(ent_id, canonical_name, {"entity_type": ent.get("entity_type")})
                graph.add_event_entity_edge(ev_id, ent_id, ent.get("role", "PARTICIPANT"))

    # 2. Add pairwise relations
    for rel in relations:
        graph.add_event_relation_edge(
            rel["source_event_id"],
            rel["target_event_id"],
            rel["relation_type"],
            rel.get("is_verified", False),
            weight=rel.get("confidence", 0.5)
        )

    return graph
