from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from build_site import build_site
from content_ops import (
    CONFIG_DIR,
    DATA_DIR,
    build_commercial_rules,
    commercial_relevance_score,
    fetch_x_signals,
    load_json,
    load_security,
    openai_json_response,
    post_to_linkedin,
    redact_sensitive_text,
    refresh_linkedin_access_token,
    save_json,
    select_contextual_image,
    sanitize_article_html,
    sanitize_url,
    slugify,
    utc_now_iso,
    choose_candidates,
)


ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Genera y publica contenido orgánico.")
    parser.add_argument("--dry-run", action="store_true", help="No usa OpenAI y genera una pieza mock.")
    parser.add_argument("--skip-linkedin", action="store_true", help="No intenta publicar en LinkedIn.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    brand = load_json(CONFIG_DIR / "brand.json", {})
    editorial_plan = load_json(CONFIG_DIR / "editorial_plan.json", {})
    sources = load_json(CONFIG_DIR / "sources.json", {})
    security = load_security()
    posts = load_json(DATA_DIR / "posts.json", [])
    state = load_json(DATA_DIR / "state.json", {"last_run_at": None, "seen_source_urls": []})
    role = next_role(posts, editorial_plan)

    max_candidates = int(brand.get("content_rules", {}).get("max_candidates_per_run", 6))
    commercial_rules = build_commercial_rules(brand)
    candidates = choose_candidates(
        sources,
        state,
        max_candidates=max_candidates,
        security=security,
        role_id=role["id"],
        brand=brand,
    )
    if role["id"] == "hot_news":
        x_signals = fetch_x_signals(editorial_plan.get("x_signal_queries", []), security, max_items=4)
        for signal in x_signals:
            signal["commercial_score"] = commercial_relevance_score(signal, commercial_rules)
        candidates = sort_candidates_for_role(candidates + x_signals, role["id"])[:max_candidates]

    if not candidates:
        state["last_run_at"] = utc_now_iso()
        save_json(DATA_DIR / "state.json", state)
        build_site()
        print("No se encontraron candidatos nuevos.")
        return 0

    if args.dry_run:
        selection = mock_selection(candidates[0], brand, role)
        draft = mock_draft(selection, candidates[0], brand, role)
    else:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            print("Falta OPENAI_API_KEY para la ejecución normal.", file=sys.stderr)
            return 1
        selection = select_topic(api_key, brand, candidates, role, editorial_plan)
        selected_candidate = match_candidate(selection, candidates)
        draft = draft_article(api_key, brand, selection, selected_candidate, role)

    selected_candidate = match_candidate(selection, candidates)
    post = assemble_post(draft, selected_candidate, brand, posts, security)
    post["editorial_role"] = role
    image_query = draft.get("image_query") or selection.get("image_query") or post["title"]
    image = select_contextual_image(image_query)
    if image:
        post["cover_image"] = image

    if args.dry_run:
        preview = {
            "dry_run": True,
            "selected_candidate": {
                "title": selected_candidate.get("title"),
                "source_name": selected_candidate.get("source_name"),
                "link": selected_candidate.get("link"),
                "commercial_score": selected_candidate.get("commercial_score"),
            },
            "post_preview": {
                "title": post["title"],
                "slug": post["slug"],
                "canonical_url": post["canonical_url"],
                "editorial_role": role.get("id"),
                "linkedin_excerpt": post.get("linkedin_text", "")[:280],
            },
        }
        print(json.dumps(preview, ensure_ascii=False, indent=2))
        print("Dry-run completado sin modificar posts.json, state.json ni el sitio.")
        return 0

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


def select_topic(
    api_key: str,
    brand: dict[str, Any],
    candidates: list[dict[str, Any]],
    role: dict[str, Any],
    editorial_plan: dict[str, Any],
) -> dict[str, Any]:
    discovery_model = os.getenv("OPENAI_MODEL_DISCOVERY", brand.get("models", {}).get("discovery", "gpt-5.4-nano"))
    instructions = """
Eres un estratega editorial B2B para una consultora de automatización e integración de IA.
Debes elegir un solo tema con mayor potencial de atraer clientes empresariales.
La selección debe favorecer temas donde haya tensión, riesgo, contradicción u oportunidad operativa clara.
Evita temas demasiado genéricos, celebratorios o puramente técnicos sin implicación de negocio.
Cuida siempre la ortografía, la puntuación y la acentuación.
Responde solo con JSON válido.
"""
    payload = json.dumps(
        {
            "company": brand.get("company_name"),
            "positioning": brand.get("positioning_statement"),
            "contrarian_thesis": brand.get("contrarian_thesis"),
            "services": brand.get("services", []),
            "goals": brand.get("editorial_goals", []),
            "audience": brand.get("audience", []),
            "voice": brand.get("voice", {}),
            "editorial_role": role,
            "role_hint": editorial_plan.get("role_hints", {}).get(role["id"]),
            "candidates": candidates,
            "required_output": {
                "selected_url": "url elegida",
                "blog_title": "título del artículo en español",
                "slug": "slug breve",
                "angle": "ángulo comercial y editorial",
                "why_it_matters": "por qué importa para empresas",
                "image_query": "busqueda breve para imagen editorial",
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
    role: dict[str, Any],
) -> dict[str, Any]:
    writing_model = os.getenv("OPENAI_MODEL_WRITING", brand.get("models", {}).get("writing", "gpt-5.4-mini"))
    instructions = """
Eres un editor senior de contenidos para una consultora que vende proyectos de automatización e IA.
Escribe en español para directivos y responsables de operaciones.
El artículo debe tener ritmo de blog premium: una apertura provocadora, frases largas combinadas con frases cortas contundentes, una tesis clara, storytelling ejecutivo y cierre consultivo.
No escribas como whitepaper. No escribas como nota corporativa. Escribe como una pieza que abre una conversación comercial inteligente.
Cada artículo debe:
- abrir con tensión o contradicción;
- incluir una frase breve y afilada como golpe editorial;
- bajar la tendencia al terreno operativo;
- incluir ejemplos, listas útiles y un cierre con siguiente paso.
La voz debe sonar a una consultora boutique, estratégica, frontal y sobria. Debe notarse criterio. Nunca grandilocuencia.
Evita frases y lugares comunes corporativos. Si una frase suena intercambiable con la de cualquier agencia, reescríbela.
Cuida siempre la ortografía, la puntuación y la acentuación. No entregues texto con errores ortográficos.
No incluyas datos personales, emails, teléfonos, datos privados, secretos ni información confidencial.
Responde solo con JSON válido.
El campo article_html debe contener solo HTML interno del artículo, sin html ni body.
El campo linkedin_text debe cerrar con el placeholder {{ARTICLE_URL}}.
"""
    payload = json.dumps(
        {
            "brand": brand,
            "selection": selection,
            "primary_candidate": candidate,
            "positioning": brand.get("positioning_statement"),
            "contrarian_thesis": brand.get("contrarian_thesis"),
            "voice": brand.get("voice", {}),
            "editorial_role": role,
            "limits": brand.get("content_rules", {}),
            "required_output": {
                "title": "título final",
                "deck": "subtítulo breve que sostenga la tesis",
                "slug": "slug final",
                "excerpt": "resumen corto de 140 a 180 caracteres",
                "seo_description": "meta descripción corta",
                "pull_quote": "frase breve y memorable",
                "key_takeaways": ["idea 1", "idea 2", "idea 3"],
                "cover_label": "etiqueta corta para portada",
                "cover_theme": "signal, risk, growth o systems",
                "cta_title": "título corto para cierre",
                "cta_body": "párrafo final de CTA consultivo",
                "image_query": "consulta corta y concreta para encontrar una imagen libre relevante",
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
        "deck": redact_sensitive_text(
            draft.get("deck") or draft.get("excerpt") or candidate.get("summary", "")[:180],
            enabled=security.get("redact_patterns", True),
        ),
        "slug": slug,
        "excerpt": redact_sensitive_text(
            draft.get("excerpt") or candidate.get("summary", "")[:160],
            enabled=security.get("redact_patterns", True),
        ),
        "seo_description": redact_sensitive_text(
            draft.get("seo_description") or candidate.get("summary", ""),
            enabled=security.get("redact_patterns", True),
        ),
        "pull_quote": redact_sensitive_text(
            draft.get("pull_quote") or "La automatización sin criterio genera ruido. La automatización bien probada genera margen.",
            enabled=security.get("redact_patterns", True),
        ),
        "key_takeaways": [redact_sensitive_text(item, enabled=security.get("redact_patterns", True)) for item in draft.get("key_takeaways", [])[:3]],
        "cover_label": redact_sensitive_text(
            draft.get("cover_label") or "Análisis",
            enabled=security.get("redact_patterns", True),
        ),
        "cover_theme": draft.get("cover_theme") or "signal",
        "cta_title": redact_sensitive_text(
            draft.get("cta_title") or "Llevemos esta idea a un piloto serio.",
            enabled=security.get("redact_patterns", True),
        ),
        "cta_body": redact_sensitive_text(
            draft.get("cta_body")
            or "Si quieres convertir esta tendencia en una iniciativa aterrizada, podemos ayudarte a definir alcance, riesgos, métricas y una primera prueba controlada.",
            enabled=security.get("redact_patterns", True),
        ),
        "keywords": draft.get("keywords", []),
        "image_query": draft.get("image_query"),
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
    linkedin_requested = bool(
        organization_urn and (access_token or (refresh_token and client_id and client_secret and redirect_uri))
    )

    if refresh_token and client_id and client_secret and redirect_uri:
        refreshed = refresh_linkedin_access_token(
            client_id=client_id,
            client_secret=client_secret,
            refresh_token=refresh_token,
            redirect_uri=redirect_uri,
        )
        if refreshed and refreshed.get("access_token"):
            access_token = refreshed["access_token"]

    if not linkedin_requested:
        post["linkedin"] = {
            "status": "skipped",
            "post_reference": None,
        }
        return

    if not organization_urn or not access_token:
        post["linkedin"] = {
            "status": "error",
            "post_reference": None,
        }
        raise RuntimeError("LinkedIn esta configurado, pero no se pudo resolver un access token valido.")

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
        raise


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


def mock_selection(candidate: dict[str, Any], brand: dict[str, Any], role: dict[str, Any]) -> dict[str, Any]:
    return {
        "selected_url": candidate["link"],
        "blog_title": f"Qué significa para las empresas: {candidate['title']}",
        "slug": slugify(candidate["title"]),
        "angle": f"Cómo convertir la novedad en una oportunidad de {brand.get('services', ['automatización'])[0]}",
        "why_it_matters": "Permite aterrizar una novedad del mercado en casos de uso empresariales concretos.",
        "image_query": f"{role['label']} enterprise automation AI",
        "source_urls": [candidate["link"]],
    }


def mock_draft(selection: dict[str, Any], candidate: dict[str, Any], brand: dict[str, Any], role: dict[str, Any]) -> dict[str, Any]:
    title = selection["blog_title"]
    services = ", ".join(brand.get("services", [])[:3])
    article_html = f"""
<p>La conversación alrededor de <strong>{candidate['title']}</strong> no solo importa por novedad técnica. También abre una ventana para que las empresas revisen dónde pueden capturar valor real con {services}.</p>
<h2>Por qué vale la pena prestarle atención</h2>
<p>{selection['why_it_matters']}</p>
<p>Cuando una noticia, investigación o buena práctica gana tracción, normalmente deja ver una tendencia más profunda: mayor madurez tecnológica, menores barreras de adopción o nuevas formas de integrar IA en procesos existentes.</p>
<h2>Cómo lo traducimos a una agenda ejecutiva</h2>
<p>En una consultora de automatización, el criterio clave no es si una tecnología suena impresionante, sino si reduce tiempos, errores, retrabajo o fricción entre sistemas y equipos.</p>
<ul>
  <li>Identificar el proceso donde existe más fricción operativa.</li>
  <li>Definir una integración con impacto visible en menos de 90 días.</li>
  <li>Conectar la iniciativa con indicadores de negocio y no solo con experimentación.</li>
</ul>
<h2>Qué debería hacer una empresa ahora</h2>
<p>El siguiente paso sensato es evaluar dónde la novedad puede convertirse en una mejora operativa concreta. A partir de ahí, conviene priorizar automatizaciones con datos disponibles, dueños claros y un retorno fácil de medir.</p>
<p>Si quieres convertir esta tendencia en una hoja de ruta real para tu operación, una evaluación corta de procesos suele ser el mejor punto de partida.</p>
"""
    linkedin_text = (
        f"{title}\n\n"
        f"La noticia de hoy no importa solo por innovación. También deja ver oportunidades concretas para automatizar procesos, integrar IA y mejorar operaciones sin caer en hype.\n\n"
        f"En el artículo aterrizamos implicaciones reales para empresas y cómo convertir la tendencia en una iniciativa con retorno.\n\n"
        f"Lee la pieza completa: {{ARTICLE_URL}}"
    )
    return {
        "title": title,
        "deck": "Una lectura ejecutiva para traducir una novedad técnica en decisiones operativas con retorno.",
        "slug": selection["slug"],
        "excerpt": "Análisis ejecutivo sobre una novedad de IA y su traducción a decisiones reales de automatización empresarial.",
        "seo_description": "Artículo sobre automatización e IA aplicada a empresas a partir de una fuente reciente del sector.",
        "pull_quote": "La tecnología impresiona. El criterio operativo convierte.",
        "key_takeaways": [
            "Una noticia vale cuando puede convertirse en una mejora operativa medible.",
            "La prioridad no es experimentar más. Es reducir fricción y retrabajo.",
            "Un piloto corto y bien acotado suele ganar más que un roadmap inflado."
        ],
        "cover_label": "Análisis",
        "cover_theme": "signal",
        "cta_title": "Convirtamos la tendencia en un plan real.",
        "cta_body": "Si quieres bajar esta tendencia a una iniciativa concreta, te ayudamos a definir alcance, proceso y retorno esperado.",
        "image_query": selection.get("image_query") or f"{role['label']} automation",
        "keywords": ["automatización empresarial", "IA en empresas", "integración de IA"],
        "article_html": article_html.strip(),
        "linkedin_text": linkedin_text,
        "source_urls": [candidate["link"]],
    }


def next_role(posts: list[dict[str, Any]], editorial_plan: dict[str, Any]) -> dict[str, Any]:
    sequence = editorial_plan.get("role_sequence", [])
    if not sequence:
        return {"id": "hot_news", "label": "Hot news", "goal": "capturar atención con actualidad"}
    return sequence[len(posts) % len(sequence)]


def sort_candidates_for_role(candidates: list[dict[str, Any]], role_id: str) -> list[dict[str, Any]]:
    def sort_key(item: dict[str, Any]) -> tuple[int, float]:
        source_type = item.get("source_type", "")
        commercial_score = item.get("commercial_score", 0)
        published = item.get("published_at")
        ts = 0.0
        if published:
            try:
                ts = datetime_from_iso(published).timestamp()
            except ValueError:
                ts = 0.0
        if role_id == "hot_news":
            type_rank = {"x_signal": 0, "vendor": 1, "research": 2, "education": 3}.get(source_type, 4)
            return (-commercial_score, type_rank, -ts)
        return (-commercial_score, 0, -ts)

    deduped: dict[str, dict[str, Any]] = {}
    for candidate in candidates:
        deduped[candidate["link"]] = candidate
    return sorted(deduped.values(), key=sort_key)


def datetime_from_iso(value: str):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


if __name__ == "__main__":
    raise SystemExit(main())
