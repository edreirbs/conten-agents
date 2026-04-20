# Content Agents

Automatizacion de contenido organico para una consultora de automatizaciones e integracion de IA en empresas.

## Que hace

Este repositorio monta un motor de contenido de costo minimo basado en:

- GitHub Actions como orquestador.
- OpenAI para seleccionar tema, redactar el blog y generar la version corta para LinkedIn.
- Pexels y Unsplash como proveedores opcionales de imagen editorial libre.
- X como radar opcional de actualidad para el rol de `hot news`.
- GitHub Pages como hosting del blog estatico.
- LinkedIn Posts API para publicar en la pagina de empresa.

El flujo pensado es:

1. Lee fuentes RSS de noticias, investigacion, divulgacion y buenas practicas.
2. Rota semanalmente entre 4 roles editoriales: `hot news`, `buena practica`, `tool deep dive` y `reflexivo`.
3. Selecciona el tema con mayor relevancia comercial para la consultora.
4. Busca una imagen libre y contextual con preferencia por Pexels/Unsplash.
5. Redacta el articulo largo orientado a SEO y conversion.
6. Genera una version corta para LinkedIn con referencia al blog.
7. Publica el nuevo post en el sitio estatico.
8. Publica el resumen en LinkedIn si hay credenciales configuradas.

## Modo seguro por defecto

El proyecto ya viene preparado para minimizar fugas:

- solo trabaja con fuentes publicas;
- limpia query strings y fragmentos de URLs;
- redacta patrones sensibles antes de llamar al LLM;
- no guarda extractos de fuentes en disco;
- usa `store: false` en OpenAI;
- mantiene LinkedIn opcional hasta que actives sus credenciales.

## Estructura

- `config/brand.json`: identidad editorial y parametros del sitio.
- `config/editorial_plan.json`: rotacion de roles y reglas del calendario editorial.
- `config/sources.json`: feeds RSS monitoreados.
- `data/posts.json`: historial de posts generados.
- `data/state.json`: estado interno del pipeline.
- `scripts/run_pipeline.py`: flujo principal.
- `scripts/build_site.py`: generacion del sitio estatico.
- `.github/workflows/content-engine.yml`: ejecucion programada.

## Secrets de GitHub recomendados

Configura estos secrets en el repositorio:

- `OPENAI_API_KEY`

Opcionales para activar LinkedIn:

- `LINKEDIN_ACCESS_TOKEN`
- `LINKEDIN_ORGANIZATION_URN`

Opcionales:

- `OPENAI_MODEL_DISCOVERY`
- `OPENAI_MODEL_WRITING`
- `PEXELS_API_KEY`
- `UNSPLASH_ACCESS_KEY`
- `X_BEARER_TOKEN`
- `LINKEDIN_CLIENT_ID`
- `LINKEDIN_CLIENT_SECRET`
- `LINKEDIN_REFRESH_TOKEN`
- `LINKEDIN_REDIRECT_URI`
- `LINKEDIN_VERSION`

## Sobre LinkedIn

La publicacion automatica usa la API oficial de LinkedIn para organizaciones. En la practica:

- necesitas una app aprobada con acceso a Community Management / Posts API;
- el usuario autenticado debe ser admin de la pagina;
- un `access_token` puede bastar para arrancar;
- `refresh_token` programatico solo aplica si LinkedIn habilita esa capacidad para tu app.

Si no hay credenciales de LinkedIn, el pipeline sigue generando el articulo y deja lista la pagina.

## Configuracion minima de verdad

Si quieres hacer lo menos posible:

1. Sube el repo.
2. Activa GitHub Pages en `/docs`.
3. Crea solo el secret `OPENAI_API_KEY`.
4. Ajusta `config/brand.json` con el nombre real de la consultora y propuesta de valor.

Con eso ya queda funcionando el blog automatico. LinkedIn lo puedes prender despues sin tocar el codigo.

## Rotacion editorial

El calendario queda pensado para una publicacion por semana:

1. `Hot news`: actualidad con angulo de negocio.
2. `Buena practica`: checklist, guia o framework aplicable.
3. `Tool deep dive`: explicacion a fondo de una herramienta o tecnologia.
4. `Reflexivo`: tesis propia, error comun o marco de decision.

La secuencia esta en `config/editorial_plan.json`.

## Imagenes

La politica de imagenes es:

1. Buscar una imagen libre y contextual en Pexels.
2. Si no hay resultado y existe key, buscar en Unsplash.
3. Si no hay proveedor configurado o no hay match, usar la portada editorial SVG generada por el sitio.

Las atribuciones se muestran automaticamente cuando viene de Pexels o Unsplash.

## Publicar en GitHub Pages

La carpeta `docs/` se genera automaticamente. En GitHub:

1. Ve a `Settings > Pages`.
2. Elige `Deploy from a branch`.
3. Selecciona la rama `main`.
4. Selecciona la carpeta `/docs`.

La URL por defecto queda como:

`https://edreirbs.github.io/conten-agents/`

## Ejecucion local

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python scripts/run_pipeline.py --dry-run --skip-linkedin
```

`--dry-run` sirve para validar el flujo completo sin consumir tokens.

## Ajustes rapidos

- Edita `config/brand.json` para reflejar la propuesta de valor real de tu consultora.
- Edita `config/sources.json` si quieres agregar o quitar feeds.
- Ajusta el cron en `.github/workflows/content-engine.yml` si quieres otra frecuencia.
