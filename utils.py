import json


def parse_foto_urls(foto_raw, titolo_maglia=""):
    """Parsa i link foto da formato JSON o CSV. Fallback a placeholder.
    
    Args:
        foto_raw: Stringa JSON array o CSV di URL
        titolo_maglia: Titolo per generare placeholder
    
    Returns:
        Lista di URL puliti, almeno uno (placeholder se vuoto)
    """
    if not foto_raw:
        return [get_placeholder_image(titolo_maglia)]
    
    foto_list = []
    
    try:
        # Prova JSON
        foto_list = json.loads(foto_raw) if isinstance(foto_raw, str) else foto_raw
    except (json.JSONDecodeError, TypeError):
        # Fallback: prova CSV
        try:
            foto_list = [f.strip() for f in foto_raw.split(',') if f.strip()]
        except:
            foto_list = []
    
    # Pulisci ogni URL una sola volta (strip + quote removal)
    foto_list = [url.strip().strip('"') for url in foto_list if url]
    
    # Se vuoto, usa placeholder
    return foto_list or [get_placeholder_image(titolo_maglia)]


def get_placeholder_image(titolo_maglia):
    # Genera URL placeholder per immagine manca.
    return f'https://via.placeholder.com/300x400?text={titolo_maglia.replace(" ", "+")}'
