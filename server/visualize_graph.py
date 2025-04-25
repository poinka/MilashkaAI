import networkx as nx
import matplotlib.pyplot as plt
from app.db.kuzudb_client import KuzuDBClient
from app.core.config import settings
import logging
from app.core.rag_builder import (
    DOCUMENT_TABLE, CHUNK_TABLE, REQUIREMENT_TABLE,
    ACTOR_TABLE, ACTION_TABLE, OBJECT_TABLE, RESULT_TABLE,
    CONTAINS_RELATIONSHIP, PERFORMS_RELATIONSHIP,
    COMMITS_RELATIONSHIP, ON_WHAT_PERFORMED_RELATIONSHIP,
    EXPECTS_RELATIONSHIP, DESCRIBED_BY_RELATIONSHIP
)

def create_rag_visualization(doc_id: str, output_file: str = "rag_graph.png"):
    """Create a visualization of the RAG graph for a specific document."""
    try:
        # Connect to database
        db = KuzuDBClient(settings.KUZUDB_PATH)
        db.connect()

        # Create NetworkX graph
        G = nx.DiGraph()

        # Add document node
        doc_result = db.execute(
            f"MATCH (d:{DOCUMENT_TABLE} {{doc_id: $doc_id}}) RETURN d.filename",
            {"doc_id": doc_id}
        )
        if doc_result.has_next():
            filename = doc_result.get_next()[0]
            G.add_node(doc_id, label=f"Document\n{filename}", color='lightblue')

        # Add chunks and their relationships
        chunks_query = f"""
        MATCH (d:{DOCUMENT_TABLE} {{doc_id: $doc_id}})-[:{CONTAINS_RELATIONSHIP}]->(c:{CHUNK_TABLE})
        RETURN c.chunk_id, substring(c.text, 0, 50) + '...' as preview
        """
        chunks_result = db.execute(chunks_query, {"doc_id": doc_id})
        while chunks_result.has_next():
            chunk_id, preview = chunks_result.get_next()
            G.add_node(chunk_id, label=f"Chunk\n{preview}", color='lightgreen')
            G.add_edge(doc_id, chunk_id, label='CONTAINS')

        # Add requirements and their relationships
        req_query = f"""
        MATCH (r:{REQUIREMENT_TABLE})-[:{DESCRIBED_BY_RELATIONSHIP}]->(c:{CHUNK_TABLE})
        WHERE c.doc_id = $doc_id
        RETURN r.req_id, r.type, substring(r.description, 0, 50) + '...' as preview
        """
        req_result = db.execute(req_query, {"doc_id": doc_id})
        while req_result.has_next():
            req_id, req_type, preview = req_result.get_next()
            G.add_node(req_id, label=f"{req_type}\n{preview}", color='pink')
            G.add_edge(req_id, doc_id, label='DESCRIBES')

        # Draw the graph
        plt.figure(figsize=(15, 10))
        pos = nx.spring_layout(G, k=1, iterations=50)
        
        # Draw nodes
        for node, attrs in G.nodes(data=True):
            nx.draw_networkx_nodes(G, pos, 
                                 nodelist=[node],
                                 node_color=attrs.get('color', 'white'),
                                 node_size=2000)
        
        # Draw edges
        nx.draw_networkx_edges(G, pos)
        
        # Add labels
        nx.draw_networkx_labels(G, pos, 
                              {node: attrs['label'] for node, attrs in G.nodes(data=True)},
                              font_size=8)
        edge_labels = nx.get_edge_attributes(G, 'label')
        nx.draw_networkx_edge_labels(G, pos, edge_labels, font_size=8)

        plt.title(f"RAG Graph for Document {doc_id}")
        plt.axis('off')
        plt.savefig(output_file, format='png', dpi=300, bbox_inches='tight')
        plt.close()
        
        logging.info(f"Graph visualization saved to {output_file}")
        return True

    except Exception as e:
        logging.error(f"Error creating visualization: {e}")
        return False

if __name__ == "__main__":
    import sys
    if len(sys.argv) != 2:
        print("Usage: python visualize_graph.py <doc_id>")
        sys.exit(1)
    
    doc_id = sys.argv[1]
    create_rag_visualization(doc_id)