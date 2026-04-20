from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from build_site import build_site
from content_ops import (
    CONFIG_DIR,
    DATA_DIR,
    load_json,
    load_security,
    openai_json_response,
    post_to_linkedin,
    redact_sensitive_text,
    refresh_linkedin_access_token,
    save_json,
    sanitize_article_html,
    sanitize_url,
    slugify,
    utc_now_iso,
    choose_candidates,
)


ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Genera y publica contenido organico.")
    parser.add_argument("--dry-run", action="store_true", help="No usa OpenAI y genera una pieza mock.")
    parser.add_argument("--skip-linkedin", action="store_true", help="No intenta publicar en LinkedIn.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    brand = load_json(CONFIG_DIR / "brand.json", {})
    sources = load_json(CONFIG_DIR / "sources.json", {})
    security = load_security()
    posts = load_json(DATA_DIR / "posts.json", [])
    state = load_json(DATA_DIR / "state.json", {"last_run_at": None, "seen_source_urls": []})

    max_candidates = int(brand.get("content_rules", {}).get("max_candidates_per_run", 6))
    candidates = choose_candidates(sources, state, max_candidates=max_candidates, security=security)

    if not candidates:
        state["last_run_at"] = utc_now_iso()
        save_json(DATA_DIR / "state.json", state)
        build_site()
        print("No se encontraron candidatos nuevos.")
        return 0

    if args.dry_run:
        selection = mock_selection(candidates[0], brand)
        draft = mock_draft(selection, candidates[0], brand)
    else:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            print("Falta OPENAI_API_KEY para la ejecucion normal.", file=sys.stderr)
            return 1
        selection = select_topic(api_key, brand, candidates)
        selected_candidate = match_candidate(selection, candidates)
        draft = draft_article(api_key, brand, selection, selected_candidate)

    selected_candidate = match_candidate(selection, candidates)
    post = assemble_post(draft, selected_candidate, brand, posts, security)
    posts.insert(0, post)
    state["last_run_at"] = utc_now_iso()
    state["seen_source_urls"] = unique_urls(
        state.get("seen_source_urls", []) + post.get("source_urls", []) + [selected_candidate["link"]]
    )

    if not args.skip_linkedin:
        maybe_publish_to_linkedin(post)

    save_json(DATA_DIR / "posts.json", posts)
    save_json(DATA_DIR / "state.json", state)
    build_site()
    print(f"Post generado: {post['slug']}")
    return 0


def select_topic(api_key: str, brand: dict[str, Any], candidates: list[dict[str, Any]]) -> dict[str, Any]:
    discovery_model = os.getenv("OPENAI_MODEL_DISCOVERY", brand.get("models", {}).get("discovery", "gpt-5.4-nano"))
    instructions = """
Eres un estratega editorial B2B para una consultora de automatizacion e integracion de IA.
Debes elegir un solo tema con mayor potencial de atraer clientes empresariales.
Responde solo con JSON valido.
"""
    payload = json.dumps(
        {
            "company": brand.get("company_name"),
            "services": brand.get("services", []),
            "goals": brand.get("editorial_goals", []),
            "audience": brand.get("audience", []),
            "candidates": candidates,
            "required_output": {
                "selected_url": "url elegida",
                "blog_title": "titulo del articulo en espanol",
                "slug": "slug breve",
                "angle": "angulo comercial y editorial",
                "why_it_matters": "por que importa para empresas",
                "source_urls": ["urls de apoyo relevantes"],
            },
        },
        ensure_ascii=False,
    )
    return openai_json_response(
        api_key=api_key,
        model=discovery_model,
        instructions=instructions.strip(),
        input_payload=payload,
        effort="low",
    )


def draft_article(
    api_key: str,
    brand: dict[str, Any],
    selection: dict[str, Any],
    candidate: dict[str, Any],
) -> dict[str, Any]:
    writing_model = os.getenv("OPENAI_MODEL_WRITING", brand.get("models", {}).get("writing", "gpt-5.4-mini"))
    instructions = """
Eres un editor senior de contenidos para una consultora que vende proyectos de automatizacion e IA.
Escribe en espanol para directivos y responsables de operaciones.
El articulo debe ser claro, riguroso, accionable y comercialmente util sin sonar agresivo.
No incluyas datos personales, emails, telefonos, datos privados, secretos ni informacion confidencial.
Responde solo con JSON valido.
El campo article_html debe contener solo HTML interno del articulo, sin html ni body.
El campo linkedin_text debe cerrar con el placeholder {{ARTICLE_URL}}.
"""
    payload = json.dumps(
        {
            "brand": brand,
            "selection": selection,
            "primary_candidate": candidate,
            "limits": brand.get("content_rules", {}),
            "required_output": {
                "title": "titulo final",
                "slug": "slug final",
                "excerpt": "resumen corto de 140 a 180 caracteres",
                "seo_description": "meta descripcion corta",
                "keywords": ["lista", "de", "keywords"],
                "article_html": "<p>...</p>",
                "linkedin_text": "post corto para LinkedIn con CTA y {{ARTICLE_URL}}",
                "source_urls": ["urls usadas"],
            },
        },
        ensure_ascii=False,
    )
    return openai_json_response(
        api_key=api_key,
        model=writing_model,
        instructions=instructions.strip(),
        input_payload=payload,
        effort="medium",
    )


def assemble_post(
    draft: dict[str, Any], candidate: dict[str, Any], brand: dict[str, Any], posts: list[dict[str, Any]], security: dict[str, Any]
) -> dict[str, Any]:
    raw_slug = draft.get("slug") or draft.get("title") or candidate["title"]
    slug = ensure_unique_slug(slugify(raw_slug), posts)
    canonical_url = f"{brand.get('base_url', '').rstrip('/')}/blog/{slug}.html"
    now = utc_now_iso()
    safe_urls: list[str] = []
    for url in draft.get("source_urls", []) + [candidate["link"]]:
        sanitized = sanitize_url(url, security)
        if sanitized:
            safe_urls.append(sanitized)
    return {
        "id": now,
        "title": redact_sensitive_text(draft.get("title") or candidate["title"], enabled=security.get("redact_patterns", True)),
        "slug": slug,
        "excerpt": redact_sensitive_text(
            draft.get("excerpt") or candidate.get("summary", "")[:160],
            enabled=security.get("redact_patterns", True),
        ),
        "seo_description": redact_sensitive_text(
            draft.get("seo_description") or candidate.get("summary", ""),
            enabled=security.get("redact_patterns", True),
        ),
        "keywords": draft.get("keywords", []),
        "article_html": sanitize_article_html(draft.get("article_html") or "<p>Sin contenido.</p>"),
        "linkedin_text": redact_sensitive_text(
            (draft.get("linkedin_text") or "").replace("{{ARTICLE_URL}}", canonical_url)[:2600],
            enabled=security.get("redact_patterns", True),
        ),
        "source_name": candidate.get("source_name"),
        "source_urls": unique_urls(safe_urls),
        "published_at": now,
        "canonical_url": canonical_url,
        "linkedin": {
            "status": "pending",
            "post_reference": None,
        },
    }


def maybe_publish_to_linkedin(post: dict[str, Any]) -> None:
    organization_urn = os.getenv("LINKEDIN_ORGANIZATION_URN")
    access_token = os.getenv("LINKEDIN_ACCESS_TOKEN")
    linkedin_version = os.getenv("LINKEDIN_VERSION", "202603")

    refresh_token = os.getenv("LINKEDIN_REFRESH_TOKEN")
    client_id = os.getenv("LINKEDIN_CLIENT_ID")
    client_secret = os.getenv("LINKEDIN_CLIENT_SECRET")
    redirect_uri = os.getenv("LINKEDIN_REDIRECT_URI")

    if refresh_token and client_id and client_secret and redirect_uri:
        refreshed = refresh_linkedin_access_token(
            client_id=client_id,
            client_secret=client_secret,
            refresh_token=refresh_token,
            redirect_uri=redirect_uri,
        )
        if refreshed and refreshed.get("access_token"):
            access_token = refreshed["access_token"]

    if not organization_urn or not access_token:
        post["linkedin"] = {
            "status": "skipped",
            "post_reference": None,
        }
        return

    try:
        result = post_to_linkedin(
            access_token=access_token,
            organization_urn=organization_urn,
            commentary=post["linkedin_text"],
            linkedin_version=linkedin_version,
        )
        post["linkedin"] = {
            "status": "published",
            "post_reference": result.get("post_reference"),
        }
    except Exception:  # noqa: BLE001
        post["linkedin"] = {
            "status": "error",
            "post_reference": None,
        }


def unique_urls(urls: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for url in urls:
        if not url or url in seen:
            continue
        seen.add(url)
        unique.append(url)
    return unique


def ensure_unique_slug(slug: str, posts: list[dict[str, Any]]) -> str:
    existing = {post["slug"] for post in posts}
    if slug not in existing:
        return slug
    suffix = 2
    while f"{slug}-{suffix}" in existing:
        suffix += 1
    return f"{slug}-{suffix}"


def match_candidate(selection: dict[str, Any], candidates: list[dict[str, Any]]) -> dict[str, Any]:
    selected_url = selection.get("selected_url")
    for candidate in candidates:
        if candidate["link"] == selected_url:
            return candidate
    return candidates[0]


def mock_selection(candidate: dict[str, Any], brand: dict[str, Any]) -> dict[str, Any]:
    return {
        "selected_url": candidate["link"],
        "blog_title": f"Que significa para las empresas: {candidate['title']}",
        "slug": slugify(candidate["title"]),
        "angle": f"Como convertir la novedad en una oportunidad de {brand.get('services', ['automatizacion'])[0]}",
        "why_it_matters": "Permite aterrizar una novedad del mercado en casos de uso empresariales concretos.",
        "source_urls": [candidate["link"]],
    }


def mock_draft(selection: dict[str, Any], candidate: dict[str, Any], brand: dict[str, Any]) -> dict[str, Any]:
    title = selection["blog_title"]
    services = ", ".join(brand.get("services", [])[:3])
    article_html = f"""
<p>La conversacion alrededor de <strong>{candidate['title']}</strong> no solo importa por novedad tecnica. Tambien abre una ventana para que las empresas revisen donde pueden capturar valor real con {services}.</p>
<h2>Por que vale la pena prestarle atencion</h2>
<p>{selection['why_it_matters']}</p>
<p>Cuando una noticia, investigacion o buena practica gana traccion, normalmente deja ver una tendencia mas profunda: mayor madurez tecnologica, menores barreras de adopcion o nuevas formas de integrar IA en procesos existentes.</p>
<h2>Como lo traducimos a una agenda ejecutiva</h2>
<p>En una consultora de automatizacion, el criterio clave no es si una tecnologia suena impresionante, sino si reduce tiempos, errores, retrabajo o friccion entre sistemas y equipos.</p>
<ul>
  <li>Identificar el proceso donde existe mas friccion operativa.</li>
  <li>Definir una integracion con impacto visible en menos de 90 dias.</li>
  <li>Conectar la iniciativa con indicadores de negocio y no solo con experimentacion.</li>
</ul>
<h2>Que deberia hacer una empresa ahora</h2>
<p>El siguiente paso sensato es evaluar donde la novedad puede convertirse en una mejora operativa concreta. A partir de ahi, conviene priorizar automatizaciones con datos disponibles, dueños claros y un retorno facil de medir.</p>
<p>Si quieres convertir esta tendencia en una hoja de ruta real para tu operacion, una evaluacion corta de procesos suele ser el mejor punto de partida.</p>
"""
    linkedin_text = (
        f"{title}\n\n"
        f"La noticia de hoy no importa solo por innovacion. Tambien deja ver oportunidades concretas para automatizar procesos, integrar IA y mejorar operaciones sin caer en hype.\n\n"
        f"En el articulo aterrizamos implicaciones reales para empresas y como convertir la tendencia en una iniciativa con retorno.\n\n"
        f"Lee la pieza completa: {{ARTICLE_URL}}"
    )
    return {
        "title": title,
        "slug": selection["slug"],
        "excerpt": "Analisis ejecutivo sobre una novedad de IA y su traduccion a decisiones reales de automatizacion empresarial.",
        "seo_description": "Articulo sobre automatizacion e IA aplicada a empresas a partir de una fuente reciente del sector.",
        "keywords": ["automatizacion empresarial", "ia en empresas", "integracion de ia"],
        "article_html": article_html.strip(),
        "linkedin_text": linkedin_text,
        "source_urls": [candidate["link"]],
    }


if __name__ == "__main__":
    raise SystemExit(main())
