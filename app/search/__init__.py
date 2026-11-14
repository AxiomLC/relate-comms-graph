"""Search: Cypher, semantic, or hybrid — whichever Relate supports natively.

VERIFIED 2026-11-14 (Relate 1.0.1, aarch64/win build):

    CREATE VECTOR INDEX vidx FOR (n:Msg) ON n.emb
      OPTIONS {indexConfig: {`vector.dimensions`: 384,
                             `vector.similarity_function`: 'cosine'}}

    CALL db.index.vector.queryNodes('vidx', 10, $embedding)
      YIELD node, score RETURN node, score ORDER BY score DESC

So semantic search is NATIVE — no sidecar index. There is no inline
`cosine_similarity()` scalar function; distance is only available through the
index, which is why hybrid search is written as "vector query, then traverse".

Query-time embedding uses `relate_comms.models.EMBED_MODEL` ("embeddinggemma")
via local Ollama. Dimension must match the index; read it from the model, do not
hardcode 384.

Not implemented. Target interface:

    POST /api/search {mode: "cypher"|"semantic"|"hybrid", query, k}
      -> {"mode", "cypher_shown", "rows"}   # cypher_shown for the transparency panel
"""
