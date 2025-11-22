from models import db, Ebook, Category
from sqlalchemy import or_

def simple_search(search_query, category_id):
    """
    This is the basic search function, identical to what's in our
    /api/search route. It searches title and author.
    """
    try:
        query = Ebook.query
        
        if search_query:
            search_term = f'%{search_query}%'
            query = query.filter(
                or_(
                    Ebook.title.ilike(search_term),
                    Ebook.author_name.ilike(search_term)
                )
            )
            
        if category_id:
            query = query.filter(Ebook.category_id == category_id)
            
        ebooks = query.order_by(Ebook.title).all()
        return ebooks
    
    except Exception as e:
        print(f"[!] Error in simple_search: {e}")
        return []

def concept_search(search_query):
    """
    This is the placeholder for our advanced "Concept Search".
    A real implementation would query a vector database or search index.
    
    Our placeholder will just do a basic search for the query
    inside the Ebook title and author name for now.
    """
    print(f"[!] Warning: Running placeholder 'concept_search' for query: '{search_query}'")
    print("[!] This is NOT searching inside the PDF content.")
    
    try:
        # In a real app, this is where you'd query Elasticsearch or Pinecone.
        # Our placeholder just calls simple_search.
        
        search_term = f'%{search_query}%'
        ebooks = Ebook.query.filter(
            or_(
                Ebook.title.ilike(search_term),
                Ebook.author_name.ilike(search_term)
            )
        ).order_by(Ebook.title).all()
        
        return {
            "success": True,
            "results": ebooks,
            "message": "Note: This is a placeholder search. Full-text content search is not implemented."
        }
        
    except Exception as e:
        print(f"[!] Error in concept_search: {e}")
        return {"success": False, "error": str(e)}