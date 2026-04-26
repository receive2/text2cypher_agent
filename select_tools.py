"""
Docstring for select_tools


from tool_search import load_faiss_vectorstore, search_tools, print_search_results, build_embeddings

emb = build_embeddings()
vs = load_faiss_vectorstore("faiss_tools", embeddings=emb)

user_query = "find employees with a specific domain email"
hits = search_tools(vs, user_query=user_query, top_l=5)

print_search_results(user_query, hits)
"""

from tool_search import load_faiss_vectorstore, search_tools, print_search_results

vs = load_faiss_vectorstore("faiss_tools_test")   
q = "which movie released in 2015?"

hits = search_tools(vs, user_query=q, top_l=3)
print_search_results(q, hits)

