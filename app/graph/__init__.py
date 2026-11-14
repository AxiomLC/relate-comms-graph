"""Graph data for the 3D view.

The UI sends which node and edge types are toggled on; this returns exactly the
slice needed to draw them. The toggle list is the whole point — a 680-chat graph
is unreadable until you can turn off `service:joined_telegram`.

Not implemented. Target interface:

    GET  /api/graph?nodes=Person,Thread&edges=IN&limit=2000
      -> {"nodes": [{"id", "label", "type"}], "edges": [{"source", "target", "type"}]}

    GET  /api/types
      -> {"node_types": [...], "edge_types": [...]}   # to populate the toggles
"""
